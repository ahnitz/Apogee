"""Single-peak specialization keeps the general scan's threshold/tie contract."""
import numpy as np
import pytest
import matchedfilter as mf


@pytest.mark.parametrize('n', [64, 128, 256, 512, 1024])
def test_single_peak_equal_maxima_and_threshold(n, monkeypatch):
    monkeypatch.setenv('MF_PBMAX', '1024')
    f = mf.MatchedFilter(n, 3, 37)
    data = np.zeros((3, n), np.complex64)
    data[:, 0] = [3 + 4j, -5j, 0]
    templates = np.zeros((37, n), np.complex64)
    templates[:, 0] = 1
    f.set_templates(templates)
    f.set_data(data)
    # A DC-only product has exactly equal magnitude at every lag. This also
    # exercises an unaligned selection and the final partially occupied packet.
    for start, count in ((0, 1), (0, 37), (1, 33)):
        for lo, hi in ((0, n), (7, n - 9), (11, 12)):
            for binsize in (hi - lo, 17, n + 3):
                for threshold in (0., 4., 5., 6.):
                    out, counts = f.run(templates=(start, count), window=(lo, hi),
                                        binsize=binsize, threshold=threshold, counts=True)
                    nbins = (hi - lo + binsize - 1) // binsize
                    expected_index = np.full((3, count, nbins), -1)
                    expected_value = np.zeros((3, count, nbins), np.complex64)
                    if threshold < 5:
                        expected_index[:2] = lo + np.arange(nbins) * binsize
                        expected_value[:2] = data[:2, :1, None]
                    np.testing.assert_array_equal(out['index'], expected_index)
                    np.testing.assert_array_equal(out['value'], expected_value)
                    np.testing.assert_array_equal(counts, (expected_index >= 0).sum(axis=-1))


@pytest.mark.parametrize('window', [(0, 4), (1, 4), (4, 9), (5, 8), (63, 64)])
def test_single_peak_merge_keeps_earliest_equal_peak(window, monkeypatch):
    monkeypatch.setenv('MF_PBMAX', '1024')
    n = 64
    f = mf.MatchedFilter(n, 1, 17)
    data = np.zeros(n, np.complex64)
    # Exact period-four correlation [0, 4, 4, 0]. The odd accumulator
    # finds lag 1 before the even accumulator finds the equal peak at lag 2.
    data[[0, n // 4, 3 * n // 4]] = [2, -1 - 1j, -1 + 1j]
    f.set_data(data[None, :])
    f.set_templates(np.ones((17, n), np.complex64))
    out = f.run(window=window, binsize=n)
    eligible = [k for k in range(*window) if k % 4 in (1, 2)]
    np.testing.assert_array_equal(out['index'], eligible[0] if eligible else -1)
    np.testing.assert_array_equal(out['value'], 4 if eligible else 0)
