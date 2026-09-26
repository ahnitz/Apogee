"""Paired calibration-transfer guard, not a population FDR certification.

CPU empirical 1%/0.1% thresholds are applied UNCHANGED to every shipped
coarse implementation. Identical seeded trials remove independent Monte
Carlo uncertainty from the backend comparison. No refinement is dispatched.
"""
import ctypes
import pathlib
import re

import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu, vulkan_runs

TRIALS = 32768
BATCH = 512
BANDS = (64, 128, 256, 512, 1024, 2048)


class VulkanCoarse:
    """Dispatch a named shipped coarse kernel, including inactive options."""
    def __init__(self, band, filename):
        from matchedfilter import _vkcompute as V
        self.v = V
        self.ctx = c = V.Context(0)
        self.tiled = filename.startswith('coarse_')
        self.half = '_c16' in filename
        m = re.search(r'_c16(?:p(\d+))?(?:t(\d+))?', filename)
        ppg, tile = (int(m[1] or 1), int(m[2] or 1)) if m else (1, 1)
        group_pairs = 4 if self.tiled else ppg * tile
        self.buffers = []
        try:
            size = 4 if self.half else 8
            for length, readback in [(BATCH*band*size, False),
                                     (4*band*size, False),
                                     (BATCH*4*4, True), (BATCH*4*8, True)]:
                self.buffers.append(V._Buffer(c, length, readback=readback))
            bd, bt, bi, bv = self.buffers
            pipe, layout, setl = c._build_pipeline(
                ('fdr', filename), filename, 3 if self.tiled else 4,
                8 if self.tiled else 28)
            ds = c._descriptor_set(setl, [bd, bt, bv] if self.tiled else self.buffers)
            self.cmd = cmd = V._vp()
            V._check(c.vk.vkAllocateCommandBuffers(c.device, ctypes.byref(
                V._CmdBufAlloc(40, None, c.command_pool, 0, 1)), ctypes.byref(cmd)),
                'allocate FDR command')
            V._check(c.vk.vkBeginCommandBuffer(cmd, ctypes.byref(
                V._CmdBufBegin(42, None, 0, None))), 'begin FDR command')
            c.vk.vkCmdBindPipeline(cmd, V._BIND_POINT_COMPUTE, pipe)
            c.vk.vkCmdBindDescriptorSets(cmd, V._BIND_POINT_COMPUTE, layout,
                                        0, 1, (V._vp*1)(ds), 0, None)
            pc = ((ctypes.c_uint32*2)(4, BATCH*4) if self.tiled else
                  (ctypes.c_uint32*7)(4, 0, band, band, band.bit_length()-1, 1, 0))
            c.vk.vkCmdPushConstants(cmd, layout, V._STAGE_COMPUTE, 0,
                                    ctypes.sizeof(pc), ctypes.byref(pc))
            c.vk.vkCmdDispatch(cmd, BATCH*4//group_pairs, 1, 1)
            V._check(c.vk.vkEndCommandBuffer(cmd), 'end FDR command')
        except Exception:
            self.close()
            raise

    def run(self, data, templates):
        convert = self.v._pack_half2 if self.half else np.ascontiguousarray
        self.buffers[0].write(convert(data))
        self.buffers[1].write(convert(templates))
        self.ctx._submit(self.cmd)
        value = self.buffers[3].read(np.float32, BATCH*4*2).view(np.complex64)
        return (value.real if self.tiled else np.abs(value)).reshape(BATCH, 4)

    def close(self):
        for buf in self.buffers:
            buf.destroy()
        self.buffers = []
        self.ctx.destroy()


def assert_transfer(cpu, gpu, label):
    """Bound both signed rate drift and cancelling admission disagreements."""
    assert np.isfinite(gpu).all(), label
    # A global scale bias can corrupt other calibration cells even when no
    # trial happens to straddle this particular threshold.
    np.testing.assert_allclose(gpu, cpu, rtol=.006, atol=2e-4, err_msg=label)
    rates = {}
    ordered = np.sort(cpu)
    for fd in (.01, .001):
        count = max(1, round(fd * cpu.size))
        threshold = (float(ordered[count-1]) + float(ordered[count])) / 2
        a, b = cpu < threshold, gpu < threshold
        budget = max(1, int(np.ceil(.125 * count)))
        disagreement = np.count_nonzero(a != b)
        assert disagreement <= budget, (
            f'{label}: target FDR={fd:g}, threshold={threshold:.8g}, '
            f'CPU={a.sum()}/{cpu.size}, GPU={b.sum()}/{cpu.size}, '
            f'paired disagreements={disagreement}, budget={budget}')
        rates[str(fd)] = dict(cpu=float(a.mean()), gpu=float(b.mean()),
                              disagreements=int(disagreement), trials=int(cpu.size))
    return rates


@pytest.mark.parametrize('band', BANDS)
def test_coarse_kernel_fdr_transfer(band, record_property):
    dev = usable_gpu()
    if dev is None:
        pytest.skip('no usable GPU')
    vk, _ = vulkan_runs()
    kernels = []
    gpu = None
    try:
        if vk:
            root = pathlib.Path(mf.__file__).parent / 'spirv'
            names = [f'tierb_{band}.spv']
            names += sorted(p.name for p in root.glob(f'tierb_{band}_c16*.spv'))
            if (root / f'coarse_{band}.spv').exists():
                names.append(f'coarse_{band}.spv')
            for name in names:
                kernels.append((name, VulkanCoarse(band, name)))
        else:
            # Metal production coarse execution uses the fp32 tier-B kernel.
            gpu = mf.MatchedFilter(band, BATCH, 4, device=dev)
            kernels = [('Metal tier-B', None)]
        cpu = mf.MatchedFilter(band, BATCH, 4, device='cpu')
        rng = np.random.default_rng(91027 + band)
        k = np.arange(band)
        # Different widths/phases exercise template tiling as well as packing.
        power = np.exp(-k[None, :] / (band / np.array([2., 4., 6., 8.])[:, None]))
        power /= power.sum(axis=1, keepdims=True)
        templates = (np.sqrt(power) * np.exp(1j*rng.uniform(-np.pi, np.pi,
                                                          (4, band)))).astype(np.complex64)
        cpu.set_templates(templates)
        if gpu is not None:
            gpu.set_templates(templates)
        reference, observed = [], {name: [] for name, _ in kernels}
        matched = np.arange(BATCH) % 4
        for _ in range(TRIALS // BATCH):
            # Fractional coarse lags model a fine-grid injection between
            # coarse samples. Unit real/imag noise matches calibration tools.
            lag = rng.integers(0, 8*band, BATCH) / 8
            signal = templates[matched] * np.exp(-2j*np.pi*lag[:, None]*k/band)
            data = (rng.normal(size=(BATCH, band)) +
                    1j*rng.normal(size=(BATCH, band)) + 5.5*signal).astype(np.complex64)
            # Exact fine-grid sample at the injected lag of an 8*band
            # transform with zero power outside this band. Retain only
            # signals known to trigger the fine filter at SNR 5.5. This
            # conditions the dismissal statistic without running refinement
            # (or hundreds of thousands of long reference FFTs).
            fine = np.abs(np.sum(data.astype(np.complex128) * np.conj(signal), axis=1))
            detected = fine >= 5.5
            cpu.set_data(data)
            a = np.abs(cpu.run()['value']).reshape(BATCH, 4)
            reference.append(a[np.arange(BATCH), matched][detected])
            for name, kernel in kernels:
                if kernel is None:
                    gpu.set_data(data)
                    b = np.abs(gpu.run()['value']).reshape(BATCH, 4)
                else:
                    b = kernel.run(data, templates)
                observed[name].append(b[np.arange(BATCH), matched][detected])
        a = np.concatenate(reference)
        assert a.size >= 15000  # at least 15 observations in the 0.1% tail
        for name, values in observed.items():
            rates = assert_transfer(a, np.concatenate(values), f'band={band} {name}')
            record_property(name, str(rates))
    finally:
        for _, kernel in kernels:
            if kernel is not None:
                kernel.close()
        if gpu is not None:
            gpu._gpu.destroy()


def test_fdr_guard_rejects_a_scale_drift():
    # Prove the rate guard is sensitive even below its pointwise tolerance.
    cpu = np.linspace(2, 6, TRIALS)
    with pytest.raises(AssertionError, match='target FDR'):
        assert_transfer(cpu, cpu * .996, 'injected drift')
