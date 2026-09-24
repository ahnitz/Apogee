"""The tiled coarse kernel against numpy, at every band it is built for.

This kernel's failure mode is silent. It is a four-step of BAND = TP * R
whose second stage must be a length-TP transform, and when that length was
wrong the kernel returned a plausible correlation magnitude -- 19% low at
band 512, 24% high at 1024 -- rather than failing. Nothing downstream can
tell such a number from a real one: a coarse estimate that is too low
quietly dismisses signals, and one that is too high quietly refines
everything.

So this compares against numpy directly rather than against another path
of the same library.
"""
import ctypes
import json
import pathlib

import numpy as np
import pytest

import matchedfilter as mf


def _bands():
    d = pathlib.Path(mf.__file__).parent / "spirv"
    return sorted(int(p.stem.split("_")[1]) for p in d.glob("coarse_*.spv"))


@pytest.mark.parametrize("band", _bands() or [pytest.param(0, marks=pytest.mark.skip)])
def test_tiled_coarse_matches_numpy(band):
    from conftest import vulkan_runs
    ok, why = vulkan_runs()
    if not ok:
        pytest.skip(why)
    from matchedfilter import _vkcompute as V

    nd, nt = 4, 8
    pairs = nd * nt
    tile = 4                      # the TILE the kernel is compiled with
    rng = np.random.default_rng(band)
    d = (rng.standard_normal((nd, band))
         + 1j * rng.standard_normal((nd, band))).astype(np.complex64)
    t = (rng.standard_normal((nt, band))
         + 1j * rng.standard_normal((nt, band))).astype(np.complex64)
    want = np.array([np.abs(np.fft.ifft(d[p // nt] * np.conj(t[p % nt])) * band).max()
                     for p in range(pairs)])

    ctx = V.Context(0)
    try:
        pipe, layout, setl = ctx._build_pipeline(
            ("coarse", band), "coarse_%d.spv" % band, 3, 8)
        bd = V._Buffer(ctx, nd * band * 8)
        bt = V._Buffer(ctx, nt * band * 8)
        bo = V._Buffer(ctx, pairs * 8, readback=True)
        bd.write(np.ascontiguousarray(d, np.complex64))
        bt.write(np.ascontiguousarray(t, np.complex64))
        ds = ctx._descriptor_set(setl, [bd, bt, bo])
        cb = V._CmdBufAlloc(40, None, ctx.command_pool, 0, 1)
        cmd = V._vp()
        ctx.vk.vkAllocateCommandBuffers(ctx.device, ctypes.byref(cb),
                                        ctypes.byref(cmd))
        ctx.vk.vkBeginCommandBuffer(
            cmd, ctypes.byref(V._CmdBufBegin(42, None, 0, None)))
        ctx.vk.vkCmdBindPipeline(cmd, V._BIND_POINT_COMPUTE, pipe)
        ctx.vk.vkCmdBindDescriptorSets(cmd, V._BIND_POINT_COMPUTE, layout, 0, 1,
                                       (V._vp * 1)(ds), 0, None)
        pc = (ctypes.c_uint32 * 2)(nt, pairs)
        ctx.vk.vkCmdPushConstants(cmd, layout, V._STAGE_COMPUTE, 0, 8,
                                  ctypes.byref(pc))
        ctx.vk.vkCmdDispatch(cmd, (pairs + tile - 1) // tile, 1, 1)
        ctx.vk.vkEndCommandBuffer(cmd)
        sub = V._SubmitInfo(4, None, 0, None, None, 1, (V._vp * 1)(cmd), 0, None)
        ctx.vk.vkQueueSubmit(ctx.queue, 1, ctypes.byref(sub), None)
        ctx.vk.vkQueueWaitIdle(ctx.queue)
        got = bo.read(np.float32, pairs * 2).view(np.complex64).real
    finally:
        ctx.destroy()

    rel = np.abs(got.astype(np.float64) - want) / want
    assert rel.max() < 2e-5, (
        "band %d coarse peak is %.1f%% off numpy (worst %.4f vs %.4f)"
        % (band, 100 * rel.max(), got[rel.argmax()], want[rel.argmax()]))
