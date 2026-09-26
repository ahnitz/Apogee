"""Adaptive CPU execution must preserve results through fallback and updates."""
import numpy as np
import pytest
import matchedfilter as mf


@pytest.mark.parametrize("n", [256, 512, 1024])
def test_adaptive_pairbatch_and_fallbacks(n, monkeypatch):
    rng = np.random.default_rng(n)
    def noise(shape):
        return (rng.normal(size=shape)+1j*rng.normal(size=shape)).astype(np.complex64)
    data, templates = noise((16,n)), noise((64,n))
    monkeypatch.setenv("MF_PBMAX", "128")
    reference = mf.MatchedFilter(n,16,64)
    monkeypatch.delenv("MF_PBMAX")
    adaptive = mf.MatchedFilter(n,16,64)
    for f in (reference,adaptive):
        f.set_data(data); f.set_templates(templates)
    for update in range(2):
        if update:
            for f in (reference,adaptive):
                f.set_data(data[10]*2j,index=10)
                f.set_templates(templates[31]*(1+1j),index=31)
        for t0,nt in ((16,16),(0,64),(0,16),(0,17),(0,24),(1,32),(16,32),(0,1)):
            for lo,hi,bs in ((0,n,n),(n//4,3*n//4,n),(100,101,n),(0,n,17)):
                kw=dict(data=(8,8),templates=(t0,nt),window=(lo,hi),binsize=bs,threshold=2*np.sqrt(n),counts=True)
                want,wc=reference.run(**kw)
                got,gc=adaptive.run(**kw)
                np.testing.assert_array_equal(got["index"],want["index"])
                np.testing.assert_allclose(got["value"],want["value"],rtol=2e-5,atol=1e-4)
                np.testing.assert_array_equal(gc,wc)


@pytest.mark.parametrize("band", [256,512,1024])
def test_hierarchical_pairbatch_matches_balanced(band,monkeypatch):
    n,nt=4096,37
    rng=np.random.default_rng(914)
    h=(rng.normal(size=(nt,n))+1j*rng.normal(size=(nt,n))).astype(np.complex64)
    series=(rng.normal(size=4*n)+1j*rng.normal(size=4*n)).astype(np.complex64)
    outputs=[]
    for cutoff in ("128",None):
        if cutoff is None: monkeypatch.delenv("MF_PBMAX")
        else: monkeypatch.setenv("MF_PBMAX",cutoff)
        f=mf.HierarchicalFilter(n,1,nt,band=band,snr=5.5,fd=1e-2)
        f.set_reference(np.ones(n,np.float32)); f.set_coarse_threshold(0.)
        f.set_templates(h)
        outputs.append(f.run_series(series,[0,n,2*n,3*n],[0,300,0,300],[n]*4,
                                     binsize=n).copy())
    assert (outputs[0]["index"]>=0).all()
    np.testing.assert_array_equal(outputs[0]["index"],outputs[1]["index"])
    np.testing.assert_allclose(outputs[0]["value"],outputs[1]["value"],rtol=2e-5,atol=1e-4)
