"""A tied argmax may choose any lag, but its value must belong to that lag."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.mark.parametrize('n', [1024, 4096, 16384, 32768, 65536])
@pytest.mark.parametrize('binsize', [None, 257, 1])
def test_tied_peak_index_and_complex_value_agree(n, binsize):
    dev = usable_gpu()
    if dev is None:
        pytest.skip('no usable GPU')
    rows = 32 if n == 16384 and binsize is None else 4
    bank = np.zeros((rows, n), np.complex64)
    bank[:, n//4] = 1
    f = mf.MatchedFilter(n, rows, rows, device=dev)
    f.set_data(bank)
    f.set_templates(bank)
    phases = np.array([1, 1j, -1, -1j], np.complex64)
    for _ in range(12 if rows == 32 else 2):
        out = f.run(binsize=binsize, window=(7, n-3))
        index = out['index']
        assert ((index >= 7) & (index < n-3)).all()
        np.testing.assert_allclose(out['value'], phases[index % 4], atol=2e-5)
        if binsize is not None:
            np.testing.assert_array_equal((index-7)//binsize,
                np.broadcast_to(np.arange(index.shape[-1]), index.shape))
    empty = f.run(binsize=binsize, threshold=2., window=(7, n-3))
    np.testing.assert_array_equal(empty['index'], -1)
    np.testing.assert_array_equal(empty['value'], 0)


@pytest.mark.parametrize('band', [64, 128, 256, 512, 1024, 2048])
def test_ties_through_coarse_compaction_and_refinement(band):
    dev = usable_gpu()
    if dev is None:
        pytest.skip('no usable GPU')
    n = 4096
    bank = np.zeros((4, n), np.complex64)
    bank[:, band//4] = 1
    f = mf.HierarchicalFilter(n, 4, 4, band=band, device=dev)
    f.set_coarse_threshold(.5)
    f.set_data(bank)
    f.set_templates(bank)
    for _ in range(3):
        out = f.run()
        assert (out['index'] >= 0).all()
        expected = np.exp(2j*np.pi*(band//4)*out['index']/n)
        np.testing.assert_allclose(out['value'], expected, atol=3e-5)
    assert f.stats == (48, 48)
