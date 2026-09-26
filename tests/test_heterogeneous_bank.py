"""A bank whose templates do not match their reference loses signals.

The coarse template is normalised by the REFERENCE's in-band fraction, not
by each template's own -- src/hmf.c refresh_template():

    double f = p->ref_on ? p->ref_f : p->fpow[t];
    double scale = f > 0 ? 1 / sqrt(f) : 0;

`fpow[t]`, the per-template fraction, is computed and then used only when no
reference is set. With a reference -- which is the normal path, since
selection needs one -- every template is scaled by the same factor. A
template that keeps less of its power in the band than the reference
implies therefore produces a coarse statistic smaller by sqrt(f_t / f_ref),
and is gated on a threshold calibrated for f_ref.

Measured at band 512, n=4096, reference f=0.9584, injections at 1.04*snr,
a 16-template bank spanning exponents -7/3 to -4/3:

    template f   0.958  0.936  0.927  0.878  0.827  0.786  0.739
    dismissed        0      0   3.3%      0  18.5%  33.3%  48.3%

Monotone in the template's own f, zero above 0.936, and 66 of 508 overall
against a 1e-3 budget.

WHY THE CAPTURED PyCBC BANK DOES NOT SHOW IT, which looked like a
contradiction for several cycles: its 37 templates run f 0.636 to 0.786
against a reference at 0.9875, a predicted shortfall of 0.80 to 0.89 --
WORSE than the synthetic case that fails -- and it dismisses 0 of 160. The
difference is headroom. That capture runs at band 1024, ratio 5.33, where
the shipped threshold audits 2.5% BELOW the safe value; the synthetic case
runs at band 512, ratio 2.83, where it audits 4.1% ABOVE. Grid loss
compounds it: the coarse maximum sits on a lag grid, and ratio 2.83 samples
the peak half as finely as 5.33.

So heterogeneous banks are not safe or unsafe in themselves. They consume
threshold headroom that nothing accounts for, and whether that is survivable
depends on the band. The contract -- one reference describing the bank --
is what the tables are calibrated against, and this is the cost of departing
from it.
"""
import numpy as np

import matchedfilter as mf
from test_api import inspiral_power, template_with_power
from _gatelib import dismissal_by_template


N = 4096
SNR = 5.0
FD = 1e-3


def test_a_matched_bank_keeps_its_signals():
    """The contract: one reference that describes the bank."""
    ref = inspiral_power(N)
    H = np.stack([template_with_power(N, ref) for _ in range(16)])
    det, om = dismissal_by_template(N, H, ref, 512, SNR, FD)
    assert det.sum() > 300, "too few detections: %d" % det.sum()
    rate = om.sum() / det.sum()
    assert rate <= 1e-2, \
        "a bank matching its reference dismissed %d of %d = %.2e" \
        % (om.sum(), det.sum(), rate)


def test_a_mismatched_bank_loses_signals_in_order_of_their_own_f():
    """Pins both the loss and its SHAPE.

    The shape is what identifies the mechanism. A flat loss across the bank
    would be a threshold that is simply too high; loss ordered by each
    template's own in-band fraction is the reference-normalisation in
    refresh_template(), and only that.
    """
    ref = inspiral_power(N)
    exps = np.linspace(-7 / 3.0, -4 / 3.0, 16)
    H = np.stack([template_with_power(N, inspiral_power(N, exponent=e))
                  for e in exps])
    det, om = dismissal_by_template(N, H, ref, 512, SNR, FD)
    assert det.sum() > 300, "too few detections: %d" % det.sum()

    fs = np.array([mf._band_features(inspiral_power(N, exponent=e), 512)[0]
                   for e in exps])
    assert fs[0] > fs[-1], "expected the bank to span a range of f"

    rate = om.sum() / det.sum()
    assert rate > 10 * FD, (
        "a bank spanning f %.3f to %.3f against a reference at %.3f now "
        "dismisses only %.2e. If refresh_template() started using fpow[t], "
        "that is the fix -- this test should then assert the loss is GONE."
        % (fs[-1], fs[0], mf._band_features(ref, 512)[0], rate))

    # The shape: templates whose own f is closest to the reference must do
    # better than those furthest from it.
    top = om[:4].sum() / max(det[:4].sum(), 1)
    bottom = om[-4:].sum() / max(det[-4:].sum(), 1)
    assert bottom > top + 0.05, (
        "loss is not ordered by the template's own f (best quartile %.2e, "
        "worst %.2e), so it is not the reference normalisation" % (top, bottom))
