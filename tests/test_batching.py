"""Batch shapes, including the ones nothing exercised until a cost sweep did.

Helpers come from test_api, which holds the signal and layout builders the
whole suite shares.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import matchedfilter as mf                                    # noqa: E402
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402


def test_data_passed_as_a_temporary_survives_the_run():
    """A caller may pass an array they do not keep.

    The plan holds the caller's pointer rather than copying: the coarse band
    is read straight out of it during the run, and the full spectrum is
    ingested lazily only if a pair fires. So `set_data(make_array())` --
    where nothing else references the array -- was a use-after-free, and one
    that only fired when the refine path actually ran, which needs a high
    trigger rate AND enough data segments. It segfaulted at 14 segments and
    passed at 12.

    This drives it deliberately: a reference concentrated enough to open the
    margin often, no name bound to the data, and enough segments and repeats to
    give the allocator a chance to reuse the freed block.

    Be honest about what it is worth: reverting the fix does NOT reliably
    fail it, because a use-after-free only crashes when the block is reused.
    It is a smoke test for the shape of the bug, not a proof. The test below,
    which simply walks batch shapes nothing had exercised, is what would have
    caught this in the first place.
    """
    n, nd = 4096, 16
    power = inspiral_power(n)
    power = np.ascontiguousarray(power, dtype=np.float32)
    rng = np.random.default_rng(1)
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=1, snr=5.0, fd=1e-3,
                               band=1024, oversample=2, taps=8)
    hf.set_reference(power)
    hf.set_templates(template_with_power(n, power)[None, :])
    for _ in range(10):
        hf.set_data(noise((nd, n), rng))     # deliberately not retained
        hf.run(binsize=n, threshold=5.0, raw=True)


def test_many_data_segments_and_templates():
    """Batch shapes beyond the ones the captures happen to use.

    The library was exercised at one or a few data segments for most of its
    life, and the shapes a cost sweep wants -- tens of segments against tens
    of templates -- went through paths nothing had run. Walk a spread of them
    and check the output stays the shape it claims.
    """
    n = 4096
    power = np.ascontiguousarray(inspiral_power(n), dtype=np.float32)
    rng = np.random.default_rng(4)
    for nt, nd in ((1, 1), (1, 16), (16, 1), (8, 8), (32, 8), (16, 16)):
        hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.0,
                                   fd=1e-3, band=1024, oversample=2, taps=8)
        hf.set_reference(power)
        hf.set_templates(np.stack([template_with_power(n, power)
                                   for _ in range(nt)]))
        for _ in range(3):
            hf.set_data(noise((nd, n), rng))
            idx, val = hf.run(binsize=n, threshold=5.0, raw=True)
            assert idx.shape == (nd, nt, 1), (nt, nd, idx.shape)
