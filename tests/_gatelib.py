"""Shared measurement for the coarse-gate tests.

Four copies of the same loop had accumulated across test_gate_population,
test_low_ratio_corner and test_heterogeneous_bank: build a bank, inject at
the design SNR, filter with the flat filter and the hierarchical one, and
count the peaks the flat filter reports that the hierarchical one does not.
They differed only in what they summed at the end.

Underscore-prefixed so pytest does not collect it as a test module.

Independent of tools/audit_threshold.py, whose injection harness provides
another check of model gate placement.
"""
import numpy as np

import matchedfilter as mf
from test_api import noise


def dismissal_by_template(n, H, reference, band, snr, fd, taps=8, reps=12,
                          nb=64, amp=1.04, seed=23, threshold=None):
    """Per-template (detected, dismissed) for injections at `amp * snr`.

    Per template rather than aggregate because the SHAPE of the loss is
    what identifies its cause: flat across the bank means the threshold is
    simply too high, ordered by the template's own in-band fraction means
    the reference normalisation in hmf.c refresh_template(). Callers that
    only want the total sum the arrays.

    `amp` slightly above 1 so an injection at the detection threshold is
    actually detected by the flat filter; a pair the flat filter misses
    says nothing about the gate.
    """
    nt = H.shape[0]
    flat = mf.MatchedFilter(n, nb, nt)
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(n, nb, nt, snr=snr, fd=fd, band=band,
                                 taps=taps)
    hier.set_reference(reference)
    hier.set_templates(H)
    if threshold is not None:
        hier.set_coarse_threshold(threshold)
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    rng = np.random.default_rng(seed)
    detected = np.zeros(nt, int)
    dismissed = np.zeros(nt, int)
    for _ in range(reps):
        D = noise((nb, n), rng)
        which = rng.integers(0, nt, nb)
        for b in range(nb):
            lag = int(rng.integers(0, n))
            D[b] += (amp * snr * H[which[b]] * ph ** lag).astype(np.complex64)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=n, threshold=snr)
        c = hier.run(binsize=n, threshold=snr)
        for b in range(nb):
            t = which[b]
            if a["index"][b, t, 0] >= 0:
                detected[t] += 1
                dismissed[t] += int(c["index"][b, t, 0] < 0)
    return detected, dismissed


def noise_trigger_loss(n, H, reference, band, snr, fd, taps=8, reps=12,
                       nb=64, seed=5):
    """(flat triggers, of which the gate dismissed) on PURE NOISE.

    Also asserts the
    one-sided guarantee, which has to hold on every population: the gate
    may dismiss, never promote.
    """
    nt = H.shape[0]
    flat = mf.MatchedFilter(n, nb, nt)
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(n, nb, nt, snr=snr, fd=fd, band=band,
                                 taps=taps)
    hier.set_reference(reference)
    hier.set_templates(H)
    rng = np.random.default_rng(seed)
    total = missed = 0
    for _ in range(reps):
        D = noise((nb, n), rng)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=n, threshold=snr)
        b = hier.run(binsize=n, threshold=snr)
        fi, hi = a["index"], b["index"]
        total += int((fi >= 0).sum())
        missed += int(((fi >= 0) & (hi < 0)).sum())
        assert int(((fi < 0) & (hi >= 0)).sum()) == 0, \
            "band %d: the gate promoted a trigger the flat filter never had" \
            % band
    return total, missed
