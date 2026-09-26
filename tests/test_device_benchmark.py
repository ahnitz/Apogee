"""Full-size sweep bounds memory and checks peak ties against the transform."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    'device_benchmark', Path(__file__).resolve().parents[1] / 'tools/bench_device_paths.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_default_batch_covers_all_lengths_with_bounded_memory():
    assert bench.default_shape(4096) == (128, 512)
    for n in bench.SUPPORTED_LENGTHS:
        nd, nt = bench.default_shape(n)
        assert nd >= 1 and nt >= 1
        assert (nd + nt) * n * 8 <= 64 << 20


def test_peak_ties_check_the_values_at_both_reported_lags():
    rho = np.zeros(64, dtype=np.complex128)
    rho[10], rho[11] = 1, 1j
    data = (np.fft.fft(rho) / 64).astype(np.complex64)[None, :]
    templates = np.ones_like(data)
    dtype = [('index', np.int64), ('value', np.complex64)]
    a, b = np.zeros((1, 1, 1), dtype=dtype), np.zeros((1, 1, 1), dtype=dtype)
    a['index'], a['value'] = 10, 1
    b['index'], b['value'] = 11, 1j
    bench.check_flat_peaks(a, b, data, templates, (0, 64))
    b['value'] = 1  # same magnitude, wrong complex value
    with pytest.raises(AssertionError):
        bench.check_flat_peaks(a, b, data, templates, (0, 64))
    b['index'], b['value'] = 12, 0  # correct value at a non-maximum
    with pytest.raises(AssertionError):
        bench.check_flat_peaks(a, b, data, templates, (0, 64))
