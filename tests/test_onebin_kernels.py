"""One-bin specialization must preserve general-kernel output and dispatch."""
import numpy as np
import pytest
import matchedfilter as mf
from matchedfilter import _vkcompute as V
from conftest import vulkan_runs


@pytest.mark.parametrize('n', [16384, 32768, 65536])
@pytest.mark.parametrize('shared', [32768, 65536])
def test_onebin_artifacts_and_selection(n, shared):
    c = V.Context.__new__(V.Context)
    c.max_shared_memory = shared
    c.max_invocations = 1024
    for refine in (False, True):
        one = c._peak_file(n, 1, refine)
        general = c._peak_file(n, 2, refine)
        assert '_onebin' in one and '_onebin' not in general
        assert one.endswith('_lds32.spv') == (shared == 32768)
        assert (V._SPIRV / one).is_file()
        assert (V._SPIRV / general).is_file()
    assert c._peak_file(4096, 1) == c._kernel_file(4096)


def test_compaction_has_one_canonical_artifact():
    files = {info['compact']['file'] for info in V._manifest()['modules'].values()}
    assert files == {'compact.spv'}
    assert (V._SPIRV / 'compact.spv').is_file()
    assert not list(V._SPIRV.glob('compact_*.spv'))


@pytest.mark.parametrize('n', [16384, 32768, 65536])
@pytest.mark.parametrize('hierarchical', [False, True])
@pytest.mark.parametrize('shared', [32768, 65536])
def test_specialized_and_general_peaks_are_identical(n, hierarchical, shared):
    ok, why = vulkan_runs()
    if not ok:
        pytest.skip(why)
    rng = np.random.default_rng(n)
    d = (rng.normal(size=(3,n))+1j*rng.normal(size=(3,n))).astype(np.complex64)
    h = (rng.normal(size=(2,n))+1j*rng.normal(size=(2,n))).astype(np.complex64)
    contexts = []
    filters = []
    try:
        for specialized in (False, True):
            f = (mf.HierarchicalFilter(n,3,2,band=256,device='gpu:0')
                 if hierarchical else mf.MatchedFilter(n,3,2,device='gpu:0'))
            if hierarchical:
                f.set_coarse_threshold(0.)
            f.set_templates(h); f.set_data(d)
            contexts.append(f._gpu)
            f._gpu.max_shared_memory = min(shared, f._gpu.max_shared_memory)
            if not specialized:
                f._gpu._peak_file = lambda n, nbins, refine=False, c=f._gpu: (
                    c._refine_file(n) if refine else c._kernel_file(n))
            filters.append(f)
        for window in [(0,n), (11,n-17)]:
            for threshold in (0., 1e10):
                for binsize in (None, n*2, n//3):
                    a,b = [f.run(window=window,threshold=threshold,binsize=binsize).copy()
                           for f in filters]
                    np.testing.assert_array_equal(a,b)
    finally:
        for context in contexts:
            context.destroy()
