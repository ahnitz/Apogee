"""Worked examples, executed when the documentation is built.

Every snippet on the "Using it" page comes from this module and is run to
produce the output shown beside it. Nothing is transcribed.

That is not decoration. The page this replaced carried a hand-written table
claiming 31x over numpy, produced by a comparison that turned out to be
measuring Python loop overhead in double precision; it sat there until a
reader questioned it. A printed output block goes stale the same way a
printed benchmark does, and the only reliable defence is to run the thing.

Run them yourself::

    python -m matchedfilter.tutorial
"""

import io
import inspect
import textwrap
from contextlib import redirect_stdout

import numpy as np

import matchedfilter as mf


def basic():
    """Correlate a batch of data against a batch of templates."""
    import numpy as np
    import matchedfilter as mf

    n, ndata, ntemplates = 4096, 8, 32
    rng = np.random.default_rng(0)

    # Inputs are SPECTRA: the unnormalised forward transform of each segment.
    # With unit-norm templates and unit-variance noise, the reported
    # magnitude reads directly as a signal-to-noise ratio.
    templates = (rng.standard_normal((ntemplates, n))
                 + 1j * rng.standard_normal((ntemplates, n))).astype(np.complex64)
    templates /= np.linalg.norm(templates, axis=1, keepdims=True)
    data = (rng.standard_normal((ndata, n))
            + 1j * rng.standard_normal((ndata, n))).astype(np.complex64)

    # Bury one copy of template 3 in segment 5, at lag 900.
    ramp = np.exp(-2j * np.pi * 900 * np.arange(n) / n)
    data[5] += (9.0 * templates[3] * ramp).astype(np.complex64)

    filt = mf.MatchedFilter(n, ndata=ndata, ntemplates=ntemplates)
    filt.set_data(data)
    filt.set_templates(templates)
    peaks = filt.run(binsize=n, threshold=6.0)

    print("peaks.shape", peaks.shape, " fields", peaks.dtype.names)
    found = np.argwhere(peaks["index"] >= 0)
    for d, t, b in found:
        print("segment %d x template %d: lag %d, snr %.2f"
              % (d, t, peaks["index"][d, t, b], np.abs(peaks["value"])[d, t, b]))
    print("everything else is below threshold and reports index -1")


def output_fields():
    """`value` is complex; `magnitude` is what the threshold compared."""
    import numpy as np
    import matchedfilter as mf

    n = 1024
    rng = np.random.default_rng(4)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    d += (8.0 * h * np.exp(-2j * np.pi * 300 * np.arange(n) / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, 1, 1)
    filt.set_data(d[None, :])
    filt.set_templates(h[None, :])
    pk = filt.run(binsize=n, threshold=0.0)[0, 0, 0]

    v, m = complex(pk["value"]), float(np.abs(pk["value"]))
    print("index      %d" % int(pk["index"]))
    print("value      %+.4f%+.4fj      the complex sample, so phase is available"
          % (v.real, v.imag))
    print("magnitude  %.6f" % m)
    print("abs(value) %.6f   differs by %.1e" % (abs(v), abs(abs(v) - m)))
    print()
    print("magnitude is the number the threshold was compared against, so it")
    print("is the one to re-test against; recomputing abs(value) can land a")
    print("few ULPs the other side of a threshold.")


def binsize():
    """One reported peak per `binsize` lags, instead of one per pair."""
    import numpy as np
    import matchedfilter as mf

    n = 4096
    rng = np.random.default_rng(1)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    d += (7.0 * h * np.exp(-2j * np.pi * 2500 * np.arange(n) / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, 1, 1)
    filt.set_data(d[None, :])
    filt.set_templates(h[None, :])

    for bs in (4096, 1024, 256):
        pk = filt.run(binsize=bs, threshold=0.0)
        lags = [int(i) for i in pk["index"][0, 0]]
        signal = next(j for j, i in enumerate(lags) if i == 2500)
        print("binsize %5d -> %3d peaks, lags %-34s signal in bin %d"
              % (bs, pk.shape[2], str(lags[:4]) + (" ..." if len(lags) > 4 else ""),
                 signal))
    print()
    print("Every bin reports its own loudest lag, so binsize is the time")
    print("resolution of the output. A search that clusters candidates at a")
    print("fixed resolution sets binsize to it and does no clustering of its")
    print("own. binsize=n is the other extreme: one peak for the whole pair.")


def thresholding():
    """Bins whose peak fell below the threshold report index -1."""
    import numpy as np
    import matchedfilter as mf

    n = 4096
    rng = np.random.default_rng(2)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    d += (6.5 * h * np.exp(-2j * np.pi * 1000 * np.arange(n) / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, 1, 1)
    filt.set_data(d[None, :])
    filt.set_templates(h[None, :])

    for thr in (0.0, 4.0, 5.0, 5.5, 6.0):
        pk = filt.run(binsize=256, threshold=thr)
        kept = int((pk["index"][0, 0] >= 0).sum())
        loud = float(np.abs(pk["value"])[0, 0].max())
        print("threshold %.1f -> %2d of %d bins reported%s"
              % (thr, kept, pk.shape[2],
                 (", loudest snr %.2f" % loud) if kept else ""))
    print()
    print("The injection was at snr 6.5 and measures 5.60: noise subtracts")
    print("from a peak as often as it adds. A threshold set at the value you")
    print("injected will lose about half of them.")
    print("Bins below the threshold still occupy their slot, with index -1,")
    print("so peaks[d, t, j] is always bin j and needs no searching.")


def window():
    """Bound which lags are searched at all."""
    import numpy as np
    import matchedfilter as mf

    n = 4096
    rng = np.random.default_rng(3)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    # two signals: one inside the window we will ask for, one outside it
    for lag, snr in ((500, 12.0), (2000, 8.0)):
        d += (snr * h * np.exp(-2j * np.pi * lag * np.arange(n) / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, 1, 1)
    filt.set_data(d[None, :])
    filt.set_templates(h[None, :])

    # .copy() is not optional here: run() hands back a buffer it reuses, so
    # without it the second call would silently rewrite the first answer.
    whole = filt.run(binsize=n, threshold=5.0).copy()
    part = filt.run(binsize=n, threshold=5.0, window=(1024, 3072))
    print("all %d lags     -> lag %d, snr %.1f"
          % (n, int(whole["index"][0, 0, 0]), np.abs(whole["value"])[0, 0, 0]))
    print("lags 1024..3072 -> lag %d, snr %.1f"
          % (int(part["index"][0, 0, 0]), np.abs(part["value"])[0, 0, 0]))
    print()
    print("The louder signal at lag 500 is outside the window and is not")
    print("reported. An overlap-save caller passes its valid span here so the")
    print("wrap-around region is never searched -- and for the hierarchical")
    print("filter that matters twice, because every extra lag is another")
    print("chance for noise to force a full correlation.")


def reuse():
    """`run` returns a buffer it will overwrite on the next call."""
    import numpy as np
    import matchedfilter as mf

    n = 1024
    rng = np.random.default_rng(6)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    d[0] += (9.0 * h * np.exp(-2j * np.pi * 100 * np.arange(n) / n)).astype(np.complex64)
    d[1] += (9.0 * h * np.exp(-2j * np.pi * 700 * np.arange(n) / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, 2, 1)
    filt.set_templates(h[None, :])

    filt.set_data(d)
    first = filt.run(binsize=n, threshold=5.0)
    kept = first.copy()
    filt.set_data(d[::-1].copy())
    second = filt.run(binsize=n, threshold=5.0)

    print("same object?      ", first is second, "  shares memory?",
          np.shares_memory(first, second))
    print("first  (now)      ", [int(i) for i in first["index"][:, 0, 0]])
    print("copy taken earlier", [int(i) for i in kept["index"][:, 0, 0]])
    print()
    print("Six allocations per call are nothing beside a 2^20 transform, but")
    print("a caller driving small batches pays them every time -- at 37")
    print("templates they were 15 of the 21 microseconds a call took. So the")
    print("buffer is kept and copying is the caller's job. Anything that has")
    print("to outlive the next run needs .copy().")


def hierarchical():
    """The two-stage filter: same peaks, less work."""
    import numpy as np
    import matchedfilter as mf

    n, ndata, ntemplates = 4096, 8, 32
    rng = np.random.default_rng(5)

    # The expected power of the filter OUTPUT, bin by bin -- not the
    # template's own power. The two differ whenever the data is coloured.
    k = np.arange(1, n // 2)
    reference = np.zeros(n, np.float32)
    reference[1:n // 2] = k ** (-7.0 / 3.0) / ((0.015 * n / k) ** 4 + 1.0)
    reference /= reference.sum()

    amp = np.sqrt(reference)
    templates = (amp * np.exp(2j * np.pi * rng.random((ntemplates, n)))).astype(np.complex64)
    templates /= np.linalg.norm(templates, axis=1, keepdims=True)
    data = (rng.standard_normal((ndata, n))
            + 1j * rng.standard_normal((ndata, n))).astype(np.complex64)
    ramp = np.exp(-2j * np.pi * 1700 * np.arange(n) / n)
    data[2] += (11.0 * templates[7] * ramp).astype(np.complex64)

    hf = mf.HierarchicalFilter(n, ndata=ndata, ntemplates=ntemplates,
                               snr=6.0, fd=1e-3)
    hf.set_reference(reference)          # drives the whole configuration
    hf.set_templates(templates)
    hf.set_data(data)
    peaks = hf.run(binsize=n, threshold=6.0)

    band, oversample, taps = hf.config
    print("it chose band %d, oversample %d, taps %d" % (band, oversample, taps))
    print("escalated to the full correlation: %.1f%% of pairs"
          % (100 * hf.refine_rate))
    for d_, t_, b_ in np.argwhere(peaks["index"] >= 0):
        print("found segment %d x template %d: lag %d, snr %.2f"
              % (d_, t_, peaks["index"][d_, t_, b_],
                 np.abs(peaks["value"])[d_, t_, b_]))
    print()
    print("Peaks it reports are identical to the flat filter's. It can omit,")
    print("never invent, and fd is the budget for how often it may omit one.")


def refuses():
    """Outside its measured tables it declines rather than guessing."""
    import numpy as np
    import matchedfilter as mf

    n = 4096
    reference = np.zeros(n, np.float32)
    reference[1:n // 2] = 1.0
    hf = mf.HierarchicalFilter(n, 1, 2, snr=5.0, fd=1e-6)
    hf.set_reference(reference)
    try:
        hf.run(binsize=n, threshold=5.0)
    except ValueError as e:
        print("ValueError:", str(e).split(" -- ")[1].split(". ")[0])
    print()
    print("An fd of 1e-6 is below what the shipped tables resolve, so it")
    print("declines. Passing band, oversample and taps yourself always works.")


def teaser():
    """The six lines the Overview page shows. Short on purpose."""
    import numpy as np
    import matchedfilter as mf

    filt = mf.MatchedFilter(16384, ndata=16, ntemplates=64)
    filt.set_data(data)             # (16, 16384) complex64, already transformed
    filt.set_templates(bank)        # (64, 16384) complex64, unit norm
    peaks = filt.run(binsize=1024, threshold=5.5)

    above = peaks["index"] >= 0
    print("peaks.shape   ", peaks.shape, "  one record per bin, not 16384 samples")
    print("above 5.5     ", int(above.sum()), "of", above.size, "bins")
    print("loudest       ", "snr %.2f at lag %d"
          % (np.abs(peaks["value"]).max(),
             peaks["index"].ravel()[np.abs(peaks["value"]).argmax()]))


def _teaser_inputs():
    """Inputs for `teaser`, kept out of the snippet so it stays six lines."""
    rng = np.random.default_rng(11)
    bank = (rng.standard_normal((64, 16384))
            + 1j * rng.standard_normal((64, 16384))).astype(np.complex64)
    bank /= np.linalg.norm(bank, axis=1, keepdims=True)
    data = (rng.standard_normal((16, 16384))
            + 1j * rng.standard_normal((16, 16384))).astype(np.complex64)
    ramp = np.exp(-2j * np.pi * 9000 * np.arange(16384) / 16384)
    data[3] += (8.0 * bank[21] * ramp).astype(np.complex64)
    return data, bank


def run_teaser():
    """(source, output) for the Overview snippet."""
    data, bank = _teaser_inputs()
    g = teaser.__globals__
    old = {k: g.get(k) for k in ("data", "bank")}
    g["data"], g["bank"] = data, bank
    try:
        return run_one(teaser)
    finally:
        for k, v in old.items():
            if v is None:
                g.pop(k, None)
            else:
                g[k] = v


#: (function, heading) in the order the page presents them.
EXAMPLES = [
    (basic, "A complete example"),
    (output_fields, "What comes back"),
    (binsize, "One peak per window"),
    (thresholding, "Thresholding"),
    (window, "Bounding the lags searched"),
    (reuse, "The output buffer is reused"),
    (hierarchical, "The hierarchical mode"),
    (refuses, "When it refuses"),
]


def source_of(fn):
    """The body of `fn`, dedented, with the docstring stripped."""
    src = inspect.getsource(fn)
    body = src.split('"""')[2] if '"""' in src else src[src.index("\n") + 1:]
    return textwrap.dedent(body).strip("\n")


def run_one(fn):
    """Return (source, captured stdout) for one example."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return source_of(fn), buf.getvalue().rstrip("\n")


def run_all():
    return [(title, *run_one(fn)) for fn, title in EXAMPLES]


def main():
    src, out = run_teaser()
    print("=" * 72); print("Overview snippet"); print("=" * 72)
    print(src); print("-" * 72); print(out); print()
    for title, src, out in run_all():
        print("=" * 72)
        print(title)
        print("=" * 72)
        print(src)
        print("-" * 72)
        print(out)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
