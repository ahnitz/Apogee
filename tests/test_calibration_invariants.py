"""Execution changes must preserve the statistic the gate was calibrated on."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=['cpu', 'gpu'])
def device(request):
    if request.param == 'cpu':
        return 'cpu'
    gpu = usable_gpu()
    if gpu is None:
        pytest.skip('no usable GPU')
    return gpu


@pytest.mark.parametrize('band', [128, 256, 512])
def test_gate_matches_reference_under_scaling_and_bank_partition(device, band):
    n, nd, nt = 1024, 12, 4
    rng = np.random.default_rng(810 + band)
    data = (rng.normal(size=(nd, n)) + 1j*rng.normal(size=(nd, n))).astype(np.complex64)
    templates = (rng.normal(size=(nt, n)) + 1j*rng.normal(size=(nt, n))).astype(np.complex64)
    templates *= np.exp(-np.arange(n)[None, :] / np.array([80, 160, 320, 640])[:, None])
    templates /= np.linalg.norm(templates, axis=1)[:, None]
    reference = np.exp(-np.arange(n)/240).astype(np.float32)
    fraction = reference[:band].astype(float).sum() / reference.astype(float).sum()
    product = data[:, None, :band].astype(np.complex128) * np.conj(templates[None, :, :band])
    coarse = np.abs(np.fft.ifft(product, axis=-1)*band).max(axis=-1)/np.sqrt(fraction)
    # Pick a gap near the middle so rounding cannot plausibly change a
    # decision. Both dismissal and admission are required, not all-survive.
    ordered = np.sort(coarse.ravel())
    lo, hi = len(ordered)//3, 2*len(ordered)//3
    gap = lo + np.argmax(np.diff(ordered)[lo:hi])
    threshold = (ordered[gap]+ordered[gap+1])/2
    assert ordered[gap+1]-ordered[gap] > .01*threshold
    admitted = coarse >= threshold
    assert admitted.any() and (~admitted).any()
    flat = mf.MatchedFilter(n, nd, nt, device='cpu')
    flat.set_data(data); flat.set_templates(templates)
    expected = flat.run().copy()
    expected['index'][~admitted] = -1
    expected['value'][~admitted] = 0

    # Reverse order and uneven partitioning exercise packed vs fallback
    # dispatch. Reciprocal scaling leaves the correlation unchanged;
    # reference amplitude must never alter its dimensionless power fraction.
    for scale, refscale, chunks in [(1., 1., [(0, 4)]),
                                    (4., 8., [(0, 1), (1, 4)])]:
        order = np.arange(nt)[::-1]
        for begin, end in chunks:
            cols = order[begin:end]
            f = mf.HierarchicalFilter(n, nd, len(cols), band=band, device=device)
            f.set_coarse_threshold(float(threshold))
            f.set_reference(reference*refscale)
            f.set_templates(templates[cols]/scale)
            f.set_data(data*scale)
            got = f.run().copy()
            np.testing.assert_array_equal(got['index'], expected['index'][:, cols])
            np.testing.assert_allclose(got['value'], expected['value'][:, cols],
                                       atol=3e-5, rtol=3e-5)
            assert f.stats == (nd*len(cols), int(admitted[:, cols].sum()))
            # A changed reference must refresh resident coarse templates.
            newref = reference.copy(); newref[:band] *= .5
            f.set_reference(newref)
            newfraction = newref[:band].astype(float).sum()/newref.astype(float).sum()
            newmask = coarse[:, cols]*np.sqrt(fraction/newfraction) >= threshold
            changed = f.run()
            np.testing.assert_array_equal(changed['index'] >= 0, newmask[..., None])


def test_threshold_lookup_is_independent_of_cost_and_reference_amplitude():
    n, band = 1024, 256
    power = np.exp(-np.arange(n)/180)
    table = {'cost': {}}
    a = mf.choose_threshold(power, n, 5., .001, band, tuning=table)
    assert a is not None
    # Timing optimization may reorder candidates, but cannot change the
    # calibrated threshold for the same configuration.
    for scale in (.125, 8.):
        tuning = dict(table, cost={(n, band): 1e-12}, fdr=[], by_ns={})
        b = mf.choose_threshold(power*scale, n, 5., .001, band, tuning=tuning)
        assert b == pytest.approx(a, rel=1e-12)


def test_shipped_cost_rows_are_finite_and_cannot_set_accuracy():
    tuning = mf._load_tuning()
    assert tuning['cost']
    assert not ({'thr', 'acc2', 'acc2r', 'fdr'} & tuning.keys())
    for key, rows in tuning['cost'].items():
        assert len(key) == 5
        assert np.isfinite(rows).all()
        assert all(cost > 0 for _, _, cost in rows)
