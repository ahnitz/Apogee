"""Does each stage of the coarse pass earn its place?

Written to answer a specific question: the GPU port is expensive, so would a
SIMPLER coarse pass -- one cheap enough to carry on a GPU without the odd
transform or the interpolator -- be good enough for both sides?

The comparison is fair in the direction that matters. An even-only gate
escalates strictly MORE than the full algorithm, so it can only omit fewer
peaks: its false-dismissal rate can improve but cannot degrade. Any loss is
therefore a loss on speed alone, and no FDR matching is needed.

Measured on a diverse bank -- templates with genuinely different power-law
slopes, so a signal matches a few and not the rest. This matters: with
near-identical templates every pair escalates, refine rates come out at
80-90%, and the question is empty.

    threshold 5.0          threshold 6.0
    even            1025            472   cycles/pair
    odd + interp     354            118
    refine          1132 @ 11.2%   1141 @ 9.6%
    ------------------------------------------
    full            2542           1759
    even-only       4452           3118   (refine at 33.5% / 22.1%)

Dropping the odd pass makes the CPU 1.75x slower at both thresholds. It
costs 7-14% of cycles and saves about 44% of runtime. So it stays, and the
GPU has to carry the whole algorithm rather than a reduced one.

Run:  MF_HMF_PROF=1 python tools/coarse_stage_value.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
import matchedfilter as mf
from test_api import inspiral_power, template_with_power, noise


def main():
    n, nd, nt = 4096, 16, 128
    rng = np.random.default_rng(7)
    ref = inspiral_power(n)
    exps = np.linspace(-7 / 3.0, -4 / 3.0, nt)
    H = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in exps])
    D = noise((nd, n), rng)
    for d, (amp, ti) in enumerate([(7.0, 30), (8.0, 90)]):
        D[d] += (amp * H[ti]
                 * np.exp(2j * np.pi * np.arange(n) * (200 + 31 * d) / n)
                 ).astype(np.complex64)

    for snr in (5.0, 5.5, 6.0, 6.5):
        dump = "/tmp/mf_coarse_%s.bin" % snr
        if os.path.exists(dump):
            os.remove(dump)
        os.environ["MF_HMF_DUMP"] = dump
        hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr, fd=1e-2)
        hf.set_reference(ref)
        hf.set_data(D)
        hf.set_templates(H)
        hf.run(binsize=n, threshold=snr)
        pairs = hf.stats[0]
        del hf                                  # closes the dump
        recs = np.frombuffer(open(dump, "rb").read(),
                             dtype=np.float32).reshape(-1, 4)
        passed_even = len(recs)
        fired = int((recs[:, 1] >= recs[:, 2]).sum())
        print("snr %.1f: pairs=%-6d even-gate=%-5d (%5.2f%%)  "
              "full=%-5d (%5.2f%%)   odd+interp saves %5.2f points"
              % (snr, pairs, passed_even, 100 * passed_even / pairs,
                 fired, 100 * fired / pairs,
                 100 * (passed_even - fired) / pairs))


if __name__ == "__main__":
    main()
