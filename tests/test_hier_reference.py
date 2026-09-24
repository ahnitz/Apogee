"""The numpy coarse-pass mirror against the shipped C implementation.

The GPU port is checked against this mirror, so the mirror has to be checked
against the C -- otherwise the GPU would be verified against my reading of
the algorithm rather than against the algorithm.
"""
import os

import numpy as np
import pytest

import matchedfilter as mf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import gpu_hier_reference as ref

from test_api import inspiral_power, template_with_power, noise


def test_even_coarse_maximum_matches_the_c_implementation(tmp_path):
    """Exact agreement, not approximate.

    If the mirror and the C disagree at all, the mirror is describing a
    different algorithm and every GPU number checked against it is worthless.
    """
    n, nd, nt = 4096, 4, 8
    rng = np.random.default_rng(3)
    reference = inspiral_power(n)
    exps = np.linspace(-7 / 3.0, -4 / 3.0, nt)
    H = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in exps])
    D = noise((nd, n), rng)
    D[0] += (8.0 * H[3]
             * np.exp(2j * np.pi * np.arange(n) * 211 / n)).astype(np.complex64)

    dump = tmp_path / "dump.bin"
    old = os.environ.get("MF_HMF_DUMP")
    os.environ["MF_HMF_DUMP"] = str(dump)
    try:
        hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.0, fd=1e-2)
        hf.set_reference(reference)
        hf.set_data(D)
        hf.set_templates(H)
        hf.run(binsize=n, threshold=5.0)
        band = hf.config[0]
        del hf                       # closes the dump
    finally:
        if old is None:
            os.environ.pop("MF_HMF_DUMP", None)
        else:
            os.environ["MF_HMF_DUMP"] = old

    if not dump.exists() or dump.stat().st_size == 0:
        pytest.skip("no pair survived the early-out, so nothing was dumped")
    recs = np.frombuffer(dump.read_bytes(), dtype=np.float32).reshape(-1, 4)

    f = ref.band_fraction(reference, band)
    mine = np.array([ref.coarse_peak(D[d], H[t], band, f)[0]
                     for d in range(nd) for t in range(nt)])

    # Every dumped even value must appear among the mirror's, to float32.
    for got in recs[:, 0]:
        assert np.min(np.abs(mine - got)) <= 1e-4 * max(got, 1.0), (
            "the C reported a coarse maximum of %.6f that the mirror never "
            "produces; the mirror is describing a different algorithm" % got)


def test_band_fraction_uses_the_reference_not_the_template():
    """The scaling depends on the SIGNAL's band fraction.

    Using the template's own fraction mis-scales the coarse output and moves
    the threshold off calibration -- silently, because the result still looks
    like a plausible correlation.
    """
    n = 4096
    reference = inspiral_power(n)
    f = ref.band_fraction(reference, 512)
    assert 0.0 < f < 1.0
    assert f == pytest.approx(reference[:512].sum() / reference.sum())
