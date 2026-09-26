"""Window scheduling preserves caller order, including native packed batches."""
import numpy as np
import pytest
import matchedfilter as mf
from matchedfilter._series import SeriesLayout
from conftest import usable_gpu


def layout(lo, hi, binsize=1024):
    return SeriesLayout(1024, np.arange(len(lo), dtype=np.uintp),
                        np.array(lo, dtype=np.uintp), np.array(hi, dtype=np.uintp), binsize)


def test_layout_groups_only_repeated_windows():
    for low in ([0]*8, [0]*4+[7]*4, list(range(8))):
        p = layout(low, [1024]*8).group()
        assert p.order is None
    p = layout([7, 0, 7, 0], [1024]*4).group()
    assert p.groups == [(0, 1024, 0, 2), (7, 1024, 2, 4)]
    np.testing.assert_array_equal(p.starts, [1, 3, 0, 2])
    np.testing.assert_array_equal(p.order, [1, 3, 0, 2])
    assert p.group() is p


def test_layout_clamps_and_validates_bins():
    assert layout([0, 0], [1024, 2000], 512).nbins == 2
    assert layout([0], [2000], 2**80).nbins == 1
    with pytest.raises(ValueError, match='same bin count'):
        layout([0, 700], [1024]*2, 512)
    with pytest.raises(ValueError, match='nonempty'):
        layout([1024], [2000])
    with pytest.raises(ValueError, match='index range'):
        layout([np.iinfo(np.uintp).max], [1024])


@pytest.mark.parametrize('device', ['cpu', 'gpu'])
@pytest.mark.parametrize('kind', ['flat', 'hier'])
@pytest.mark.parametrize('raw', [False, True])
def test_interleaved_packed_batches(device, kind, raw):
    if device == 'gpu':
        device = usable_gpu()
        if device is None:
            pytest.skip('no usable GPU')
    rng = np.random.default_rng(329)
    n, blocks, nt = 1024, 24, 16
    if kind == 'flat':
        f = mf.MatchedFilter(n, 8, nt, device=device)
    else:
        f = mf.HierarchicalFilter(n, 8, nt, band=256, device=device)
        f.set_coarse_threshold(0.)
    h = (rng.normal(size=(nt,n))+1j*rng.normal(size=(nt,n))).astype('complex64')
    series = (rng.normal(size=n*13)+1j*rng.normal(size=n*13)).astype('complex64')
    f.set_templates(h)
    starts = np.arange(blocks)*512
    lo = np.arange(blocks)%3*7
    hi = lo+900
    expected = [f.run_series(series, [a], [b], [c], binsize=256).copy()
                for a,b,c in zip(starts,lo,hi)]
    expected = np.concatenate(expected)
    result = f.run_series(series, starts, lo, hi, binsize=256, raw=raw)
    idx, val = result if raw else (result['index'], result['value'])
    np.testing.assert_array_equal(idx, expected['index'])
    np.testing.assert_allclose(val, expected['value'], atol=3e-5, rtol=3e-5)
    if raw:
        assert idx.flags.c_contiguous and val.flags.c_contiguous
