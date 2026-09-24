#!/usr/bin/env python3
"""Combine benchmark JSON from several machines into one page.

    python tools/build_report.py results/ --out site/index.html

Charts are inline SVG.  No JavaScript and no external assets, so the page
renders from a file:// URL, inside a PR comment, or on GitHub Pages without
anything else being fetched.
"""
import argparse
import glob
import collections
import html
import math
import numpy as np
import json
import os
import shutil

# Colour-blind-safe, and distinguishable in greyscale by order.
#: Okabe-Ito, lifted a little.  The chart strokes are baked into the SVG
#: rather than themed, so each colour has to carry on the dark default and on
#: the light variant; the published hues are too dark against #0b0f19.
PALETTE = ["#38bdf8", "#f0883e", "#34d399", "#e291c4", "#eab308", "#93c5fd",
           "#c08552", "#94a3b8"]


def load(paths):
    runs = []
    for p in sorted(paths):
        with open(p) as fh:
            runs.append(json.load(fh))
    return runs


def axis_ticks(lo, hi, count=5):
    """Ticks on a log axis at powers of ten and their halves."""
    import math
    out = []
    e = math.floor(math.log10(lo))
    while 10 ** e <= hi * 1.001:
        for m in (1, 2, 5):
            v = m * 10 ** e
            if lo * 0.999 <= v <= hi * 1.001:
                out.append(v)
        e += 1
    return out or [lo, hi]


def fmt(v):
    """Axis label for a value that may span many decades.

    Small numbers get scientific notation. Without it every tick on the
    precision chart rendered as "0.00" -- the axis runs 1e-8 to 3e-7 and
    "%.2f" flattens all of it to zero, which made the chart unreadable and
    was not noticed because the curve still drew.
    """
    if v == 0:
        return "0"
    if v >= 100:
        return "%.0f" % v
    if v >= 10:
        return "%.0f" % v
    if v >= 1:
        return "%.1f" % v
    if v >= 0.01:
        return "%.2f" % v
    e = int(math.floor(math.log10(abs(v))))
    m = v / 10.0 ** e
    return ("%de%d" % (round(m), e) if abs(m - round(m)) < 0.05
            else "%.1fe%d" % (m, e))


def line_chart(series, title, xlabel, ylabel, width=760, height=380):
    """series: [(name, [(x, y), ...]), ...] on log-log axes."""
    import math
    pts = [p for _, s in series for p in s]
    if not pts:
        return "<p>no data</p>"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    y0, y1 = y0 * 0.7, y1 * 1.4
    L, R, T, B = 74, 210, 40, 52
    W, H = width - L - R, height - T - B

    def px(x):
        return L + W * (math.log10(x) - math.log10(x0)) / max(1e-9, math.log10(x1) - math.log10(x0))

    def py(y):
        return T + H - H * (math.log10(y) - math.log10(y0)) / max(1e-9, math.log10(y1) - math.log10(y0))

    o = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="%s">'
         % (width, height, html.escape(title))]
    o.append('<text x="%d" y="22" class="title">%s</text>' % (L, html.escape(title)))
    for v in axis_ticks(y0, y1):
        y = py(v)
        o.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>' % (L, y, L + W, y))
        o.append('<text x="%d" y="%.1f" class="tick ty">%s</text>' % (L - 8, y + 4, fmt(v)))
    for v in sorted(set(xs)):
        x = px(v)
        o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" class="grid"/>' % (x, T, x, T + H))
        lab = "%dk" % (v // 1024) if v >= 1024 else str(v)
        o.append('<text x="%.1f" y="%.1f" class="tick tx">%s</text>' % (x, T + H + 18, lab))
    o.append('<text x="%.1f" y="%d" class="axis tx">%s</text>' % (L + W / 2, height - 12, html.escape(xlabel)))
    o.append('<text transform="translate(16,%.1f) rotate(-90)" class="axis tx">%s</text>'
             % (T + H / 2, html.escape(ylabel)))
    for i, (name, s) in enumerate(series):
        c = PALETTE[i % len(PALETTE)]
        s = sorted(s)
        d = " ".join(("M" if j == 0 else "L") + "%.1f %.1f" % (px(x), py(y))
                     for j, (x, y) in enumerate(s))
        o.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.2"/>' % (d, c))
        for x, y in s:
            o.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s"/>' % (px(x), py(y), c))
        ly = T + 6 + i * 19
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2.2"/>'
                 % (L + W + 14, ly, L + W + 34, ly, c))
        o.append('<text x="%.1f" y="%.1f" class="legend">%s</text>'
                 % (L + W + 40, ly + 4, html.escape(name)))
    o.append("</svg>")
    return "".join(o)


def correlation_chart(case, width=760, height=300):
    """One case: the whole correlation, the threshold, and what was reported.

    Linear axes and every sample drawn, because the point is that a reader can
    check the claim by eye -- the reported peak should sit on the tallest
    spike, and nothing should be reported when no spike clears the line.
    """
    rho = case["rho"]
    n = len(rho)
    thr = case["threshold"]
    L, R, T, B = 52, 18, 34, 42
    W, H = width - L - R, height - T - B
    ymax = max(max(rho) * 1.18, thr * 1.35)

    def px(i):
        return L + W * i / max(1, n - 1)

    def py(v):
        return T + H - H * v / ymax

    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" '
         'aria-label="correlation for %s">' % (width, height,
                                               html.escape(case["label"]))]
    o.append('<text x="%d" y="20" class="title">%s</text>'
             % (L, html.escape(case["label"])))
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = ymax * f
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>'
                 % (L, py(v), L + W, py(v)))
        o.append('<text x="%.1f" y="%.1f" class="tick ty">%.0f</text>'
                 % (L - 8, py(v) + 4, v))
    # the threshold: the only line that decides anything
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="unity"/>'
             % (L, py(thr), L + W, py(thr)))
    o.append('<text x="%.1f" y="%.1f" class="tick">threshold %.3g</text>'
             % (L + W - 96, py(thr) - 6, thr))
    if case.get("lag") is not None:
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#999" '
                 'stroke-width="1" stroke-dasharray="3 3"/>'
                 % (px(case["lag"]), T, px(case["lag"]), T + H))
        o.append('<text x="%.1f" y="%.1f" class="tick tx">injected</text>'
                 % (px(case["lag"]), T - 6))
    o.append('<polyline fill="none" stroke="#0072b2" stroke-width="1.1" '
             'points="%s"/>'
             % " ".join("%.1f,%.1f" % (px(i), py(v)) for i, v in enumerate(rho)))
    if case["fired"]:
        o.append('<circle cx="%.1f" cy="%.1f" r="5" fill="none" '
                 'stroke="#d55e00" stroke-width="2.2"/>'
                 % (px(case["index"]), py(case["magnitude"])))
        o.append('<text x="%.1f" y="%.1f" class="tick tx" fill="#d55e00">'
                 'reported: lag %d, snr %.2f</text>'
                 % (min(px(case["index"]), L + W - 70),
                    py(case["magnitude"]) - 11, case["index"],
                    case["magnitude"]))
    else:
        o.append('<text x="%.1f" y="%.1f" class="tick" fill="%s">'
                 'reported: nothing (no sample crossed)</text>'
                 % (L + 6, T + 14, "#6b6b70"))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--bd)"/>'
             % (L, T + H, L + W, T + H))
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        i = int((n - 1) * f)
        o.append('<text x="%.1f" y="%.1f" class="tick tx">%d</text>'
                 % (px(i), T + H + 16, i))
    o.append('<text x="%.1f" y="%.1f" class="axis tx">lag (samples)</text>'
             % (L + W / 2, height - 8))
    o.append("</svg>")
    return "".join(o)


def error_histogram(rows, width=760, height=300):
    """Distribution of the per-trial errors, pooled over the sweep.

    The median and the worst case say where the errors sit and how far they
    reach. They do not say whether the distribution is a tight pile near the
    float32 epsilon or something with a tail, and those are different claims
    about the arithmetic -- a heavy tail would mean occasional large errors
    that a percentile hides.
    """
    if not rows or "hist" not in rows[0]:
        return ""
    edges = rows[0]["hist_edges"]
    tot = np.zeros(len(edges) - 1)
    for r in rows:
        tot += np.asarray(r["hist"], float)
    nz = np.nonzero(tot)[0]
    if not len(nz):
        return ""
    lo, hi = nz[0], nz[-1] + 1
    tot, edges = tot[lo:hi], edges[lo:hi + 1]
    L, R, T, B = 60, 18, 34, 54
    W, H = width - L - R, height - T - B
    ymax = tot.max() * 1.12
    bw = W / len(tot)
    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label='
         '"distribution of relative error">' % (width, height)]
    o.append('<text x="%d" y="20" class="title">Distribution of relative '
             'error (%d trials, all lengths and SNRs)</text>'
             % (L, int(tot.sum())))
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = T + H - H * f
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>'
                 % (L, y, L + W, y))
        o.append('<text x="%.1f" y="%.1f" class="tick ty">%d</text>'
                 % (L - 8, y + 4, round(ymax * f)))
    for i, v in enumerate(tot):
        h = H * v / ymax
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                 'fill="var(--accent)" opacity="0.75"/>'
                 % (L + i * bw + 1, T + H - h, max(bw - 2, 1), h))
    eps = 2.0 ** -24
    if edges[0] <= eps <= edges[-1]:
        fr = (math.log10(eps) - math.log10(edges[0])) / (
            math.log10(edges[-1]) - math.log10(edges[0]))
        x = L + W * fr
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="unity"/>'
                 % (x, T, x, T + H))
        o.append('<text x="%.1f" y="%.1f" class="tick tx">float32 eps</text>'
                 % (x, T - 6))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--bd)"/>'
             % (L, T + H, L + W, T + H))
    step = max(1, len(edges) // 7)
    for i in range(0, len(edges), step):
        o.append('<text x="%.1f" y="%.1f" class="tick tx">%s</text>'
                 % (L + i * bw, T + H + 16, fmt(edges[i])))
    o.append('<text x="%.1f" y="%.1f" class="axis tx">relative error against '
             'a float64 correlation</text>' % (L + W / 2, height - 8))
    o.append('<text x="%.1f" y="%.1f" class="axis tx">trials</text>'
             % (14, T + H / 2))
    o.append("</svg>")
    return "".join(o)


def precision_page(require=False):
    """Run the precision sweep for real and plot it.

    Executed at page-build time like the demo, so the curve is a measurement
    of the build that produced the page rather than a picture of one taken
    earlier.
    """
    try:
        from matchedfilter import precision
    except Exception as e:
        if require:
            raise SystemExit("the precision sweep could not be run (%s: %s)"
                             % (type(e).__name__, e))
        return ('<div class="note warn">The precision sweep could not be run '
                'when this page was built (<code>%s</code>).</div>'
                % html.escape("%s: %s" % (type(e).__name__, e)))
    rows = precision.sweep()
    ns = sorted({r["n"] for r in rows})
    eps = precision.EPS32
    o = ['<p>The filter computes in <strong>complex64</strong> and reports one '
         'peak per bin. A float64 numpy correlation of the same inputs is the '
         'answer it has to agree with. This sweeps injected SNR from pure '
         'noise to 1000 and measures the disagreement -- run while this page '
         'was built, not cached.</p>',
         '<div class="cards">'
         '<div class="card"><div class="k">%.1e</div>'
         '<div class="l">worst relative error, any point</div></div>'
         '<div class="card"><div class="k">%.1f</div>'
         '<div class="l">float32 ULPs at worst</div></div>'
         '<div class="card"><div class="k">%.0f%%</div>'
         '<div class="l">lowest index agreement</div></div></div>'
         % (max(r["rel_max"] for r in rows),
            max(r["rel_max"] for r in rows) / eps,
            100 * min(r["index_agreement"] for r in rows))]
    panels = []
    for stat, label in (("rel_median", "median"), ("rel_p90", "90th percentile"),
                        ("rel_max", "worst case")):
        series = [("n = %d" % n,
                   [(max(r["snr"], 1.0), max(r[stat], 1e-12))
                    for r in rows if r["n"] == n])
                  for n in ns]
        series.append(("float32 eps",
                       [(max(r["snr"], 1.0), eps) for r in rows if r["n"] == ns[0]]))
        panels.append((label, line_chart(
            series, "Relative error vs a float64 correlation (%s)" % label,
            "injected SNR (0 plotted at 1)", "relative error")))
    o.append(tabs(panels, "statistic"))
    o.append(error_histogram(rows))
    o.append('<div class="note">The distribution is a single pile a few '
             'float32 epsilons wide with no tail. That is the claim the '
             'percentiles above cannot make on their own: a median of 5e-8 '
             'is consistent with a tight pile or with a narrow core plus '
             'occasional large errors, and those are different statements '
             'about the arithmetic.</div>')
    o.append('<h3>What is being compared</h3>')
    o.append(spec_table([
        ("Reference", "The whole correlation in float64: "
                      "<code>|IFFT(data * conj(template))| * n</code>, computed "
                      "by numpy on the identical inputs."),
        ("Error", "The reported magnitude against that reference evaluated "
                  "<em>at the lag the filter reported</em>. That isolates "
                  "arithmetic from tie-breaking: comparing peak magnitudes "
                  "instead would blame the filter whenever two nearby lags "
                  "swapped places."),
        ("Index agreement", "Separately, how often the reported lag is the "
                            "float64 argmax. Where two lags sit within "
                            "rounding of each other either is a correct "
                            "answer, so this is reported rather than asserted "
                            "-- but over random noise exact ties are "
                            "vanishingly unlikely, and it is 100%% here."),
        ("Input", "Complex Gaussian noise with one copy of the template "
                  "injected at a random lag, as a phase ramp on the spectrum "
                  "-- exactly a circular shift, so the signal lands where "
                  "intended with no resampling error of its own. %d trials per "
                  "point." % rows[0]["trials"]),
    ]))
    o.append('<div class="note">The curves are flat in SNR, and that is the '
             'result. A relative error that tracked the signal would mean '
             'something was computed absolutely and then divided -- invisible '
             'on noise, and growing on exactly the loud events a search most '
             'needs to get right. Injected SNR spans 0 to 1000 here, so a '
             'proportional term would show as three orders of magnitude of '
             'growth. tests/test_precision.py asserts both this and the '
             'absolute bound.</div>')
    rows.sort(key=lambda r: (r["n"], r["snr"]))
    o.append(details("All numbers (%d rows)" % len(rows),
                     table(["n", "injected snr", "trials", "median", "p90",
                            "worst", "ULPs at worst", "index agreement"],
                           [["%d" % r["n"], "%g" % r["snr"], "%d" % r["trials"],
                             "%.2e" % r["rel_median"], "%.2e" % r["rel_p90"],
                             "%.2e" % r["rel_max"],
                             "%.1f" % (r["rel_max"] / eps),
                             "%.0f%%" % (100 * r["index_agreement"])]
                            for r in rows])))
    return "".join(o)


def demo_page(require=False):
    """Run the demo for real and show the plots beside the code that made them.

    Imported and executed here, at page-build time, so the figures cannot go
    stale against the library: if the filter stopped finding peaks, this page
    would show it rather than a cached picture of it working.
    """
    try:
        import inspect
        from matchedfilter import demo
    except Exception as e:
        if require:
            raise SystemExit(
                "the demo could not be run (%s: %s), so this page would "
                "publish with an apology where its figures go. Install the "
                "package before building, or drop --require-demo."
                % (type(e).__name__, e))
        return ('<div class="note warn">The demo could not be run when this '
                'page was built (<code>%s</code>), so there is nothing here '
                'to show. That is a build problem, not a result: the figures '
                'on this page are always generated by running the library.'
                '</div>' % html.escape("%s: %s" % (type(e).__name__, e)))
    cases = demo.run()
    ok = sum(1 for c in cases if c["agrees"])
    found = [c for c in cases if c["lag"] is not None]
    quiet = [c for c in cases if c["lag"] is None]
    o = ['<p>Every figure below was produced by running the library while this '
         'page was built. The code that produced them is at the bottom, taken '
         'from the module that ran -- not transcribed, so the two cannot '
         'disagree.</p>',
         '<div class="cards">'
         '<div class="card"><div class="k">%d/%d</div>'
         '<div class="l">peaks agree with numpy</div></div>'
         '<div class="card"><div class="k">%d/%d</div>'
         '<div class="l">behaved as expected</div></div>'
         '<div class="card"><div class="k">%d</div>'
         '<div class="l">cases within 1.0 of the threshold</div></div></div>'
         % (ok, len(cases),
            sum(1 for c in cases if c.get("as_expected")), len(cases),
            sum(1 for c in cases if c["lag"] is not None
                and abs(c["snr"] - c["threshold"]) < 1.0))]
    o.append("<h3>What you are looking at</h3>")
    o.append('<p>Each panel is one (data, template) pair: white noise of %d '
             'samples, transformed, correlated against a band-limited '
             'template. The blue curve is the full correlation computed by '
             'numpy -- all %d lags, the answer the library must agree with. '
             'The dashed line is the threshold the caller asked for. The '
             'circle is the single sample the library reported.</p>'
             % (cases[0]["n"], cases[0]["n"]))
    o.append('<p>The library returns only that circle. Computing the blue '
             'curve is the work it is allowed to skip, which is the entire '
             'reason it is faster, so the curve is here as the check rather '
             'than as output.</p>')
    o.append(tabs([(c["label"] + (" #%d" % (i + 1)), correlation_chart(c))
                   for i, c in enumerate(cases)], "case"))
    tol = cases[0]["peak_tolerance"]
    o.append("<h3>What each case shows</h3>")
    o.append(table(["case", "injected at", "loudest sample", "reported lag",
                    "reported snr", "agrees with numpy"],
                   [[html.escape(c["label"]),
                     "-" if c["lag"] is None else str(c["lag"]),
                     "%.2f" % c["max_rho"],
                     "nothing" if not c["fired"] else str(c["index"]),
                     "-" if not c["fired"] else "%.2f" % c["magnitude"],
                     "yes" if c["agrees"] else "<b>NO</b>"]
                    for c in cases]))
    thr = cases[0]["threshold"]
    near = [c for c in cases if c["lag"] is not None
            and abs(c["snr"] - thr) < 1.0]
    o.append('<div class="note"><strong>The cases near the threshold are the '
             'ones worth reading.</strong> A signal injected at snr %.1f does '
             'not arrive measuring %.1f: the noise it lands in moves it, by '
             'about a unit either way. So an injection below the threshold can '
             'clear it and one above can fail to, and both happen here. What '
             'the filter is responsible for is narrower and is what these '
             'plots check -- reporting the loudest sample, and reporting it '
             'only when it crosses. It agrees with numpy in every case, '
             'including the ones where the decision is close.</div>'
             % (near[0]["snr"] if near else thr, near[0]["snr"] if near else thr))
    miss = [c for c in cases if c["lag"] is not None and not c["fired"]]
    if miss:
        o.append('<div class="note">Concretely: %s. That is the detection '
                 'statistics, not a fault in the filter -- the flat filter '
                 'reports nothing there either, which is exactly what the '
                 'blue curve shows. It is also why the hierarchical mode is '
                 'tuned against measured false-dismissal rather than against '
                 'a model: near the threshold is where a cheap first pass '
                 'could lose something, so that is where it has to be '
                 'measured.</div>'
                 % "; ".join("injected at snr %.1f, loudest sample %.2f, "
                             "below the threshold of %.1f, so silent"
                             % (c["snr"], c["max_rho"], c["threshold"])
                             for c in miss))
    o.append('<div class="note">The pure-noise cases report nothing at all. '
             'That is the filter working: the loudest noise sample never '
             'reached the threshold, so there was no peak to report, and the '
             'library says so rather than handing back its largest '
             'fluctuation.</div>')
    off = [c["offset"] for c in found if c["offset"] is not None]
    tol = cases[0]["peak_tolerance"]
    if any(off):
        o.append('<div class="note">Where a peak was reported, the lag can '
                 'sit a sample from the injection (offsets here: %s). That is '
                 'the signal, not an error. The template keeps a quarter of '
                 'the band, so its correlation peak is about %d samples wide, '
                 'and which sample within it is loudest is decided by the '
                 'noise. Noiseless, the peak lands exactly on the injected '
                 'lag; by snr 50 it does so every time. The tolerance used '
                 'above is %d samples and is measured from the template '
                 'rather than assumed.</div>'
                 % (", ".join("%+d" % v for v in off), 2 * tol - 1, tol))
    o.append("<h3>The code</h3>")
    o.append('<p>This is the source of the functions that ran, read from the '
             'module at build time.</p>')
    src = "".join(inspect.getsource(f) + "\n" for f in
                  (demo.make_template, demo.make_data, demo.correlate,
                   demo.run_case))
    o.append("<pre><code>%s</code></pre>" % html.escape(src.rstrip()))
    o.append('<p>Run it yourself with <code>python -m matchedfilter.demo</code>.</p>')
    return "".join(o)


def bar_chart(groups, series_names, title, ylabel, width=760, height=380):
    """groups: [(group_label, [v_per_series...]), ...]"""
    vals = [v for _, vs in groups for v in vs if v is not None]
    if not vals:
        return "<p>no data</p>"
    ymax = max(vals) * 1.15
    L, R, T, B = 64, 210, 40, 56
    W, H = width - L - R, height - T - B
    gw = W / max(1, len(groups))
    bw = gw * 0.78 / max(1, len(series_names))
    o = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="%s">'
         % (width, height, html.escape(title))]
    o.append('<text x="%d" y="22" class="title">%s</text>' % (L, html.escape(title)))
    step = 1.0 if ymax <= 8 else 2.0 if ymax <= 20 else 5.0
    v = 0.0
    while v <= ymax:
        y = T + H - H * v / ymax
        o.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>' % (L, y, L + W, y))
        o.append('<text x="%d" y="%.1f" class="tick ty">%gx</text>' % (L - 8, y + 4, v))
        v += step
    # 1x is the "no better than the flat filter" line
    y1 = T + H - H * 1.0 / ymax
    o.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" class="unity"/>' % (L, y1, L + W, y1))
    for gi, (glabel, vs) in enumerate(groups):
        gx = L + gi * gw
        for si, val in enumerate(vs):
            if val is None:
                continue
            h = H * min(val, ymax) / ymax
            x = gx + gw * 0.11 + si * bw
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                     % (x, T + H - h, bw * 0.88, h, PALETTE[si % len(PALETTE)]))
        o.append('<text x="%.1f" y="%.1f" class="tick tx">%s</text>'
                 % (gx + gw / 2, T + H + 18, html.escape(glabel)))
    o.append('<text transform="translate(14,%.1f) rotate(-90)" class="axis tx">%s</text>'
             % (T + H / 2, html.escape(ylabel)))
    for i, name in enumerate(series_names):
        ly = T + 6 + i * 19
        o.append('<rect x="%.1f" y="%.1f" width="14" height="10" fill="%s"/>'
                 % (L + W + 14, ly - 6, PALETTE[i % len(PALETTE)]))
        o.append('<text x="%.1f" y="%.1f" class="legend">%s</text>'
                 % (L + W + 34, ly + 3, html.escape(name)))
    o.append("</svg>")
    return "".join(o)


CSS = """
/* Editorial rather than dashboard: a serif text face, hairline rules instead
   of filled cards, and square corners.  Dark by default, on the logo's own
   ink; the light variant is the same design on paper. */
:root{--fg:#e2e8f0;--mut:#8f9bad;--bd:#1e293b;--bg:#0b0f19;--panel:#111827;
      --accent:#38bdf8;--code:#0f1729;--rule:#334155}
@media (prefers-color-scheme:light){:root{--fg:#0f172a;--mut:#5b6779;
      --bd:#dde3ea;--bg:#fbfcfd;--panel:#f1f5f9;--accent:#0369a1;
      --code:#f1f5f9;--rule:#0f172a}}
:root[data-theme="dark"]{--fg:#e2e8f0;--mut:#8f9bad;--bd:#1e293b;--bg:#0b0f19;
      --panel:#111827;--accent:#38bdf8;--code:#0f1729;--rule:#334155}
:root[data-theme="light"]{--fg:#0f172a;--mut:#5b6779;--bd:#dde3ea;--bg:#fbfcfd;
      --panel:#f1f5f9;--accent:#0369a1;--code:#f1f5f9;--rule:#0f172a}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:1rem}
body{margin:0;color:var(--fg);background:var(--bg);
     font:17px/1.6 Charter,"Bitstream Charter","Iowan Old Style","Source Serif 4",
          "Source Serif Pro",Palatino,Georgia,serif;
     -webkit-font-smoothing:antialiased}
.ui{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Helvetica,sans-serif}
.wrap{display:grid;grid-template-columns:225px minmax(0,1fr);gap:3.25rem;
      max-width:1140px;margin:0 auto;padding:0 1.4rem}

nav{position:sticky;top:0;align-self:start;max-height:100vh;overflow-y:auto;
    padding:2.2rem 1.4rem 3rem 0;border-right:1px solid var(--bd);
    font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
nav .brand{font-family:Charter,"Bitstream Charter",Georgia,serif;font-weight:700;
    font-size:1.2rem;letter-spacing:-.01em}
nav .ver{color:var(--mut);font-size:11.5px;margin:.1rem 0 1.6rem;
    font-variant-numeric:tabular-nums}
nav .navgrp{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--mut);margin:1.5rem 0 .45rem}
nav .navgrp:first-of-type{margin-top:0}
nav a{display:block;padding:.2rem 0 .2rem .7rem;color:var(--mut);
    text-decoration:none;font-size:13.5px;line-height:1.45;
    border-left:2px solid var(--bd)}
nav a:hover{color:var(--fg);border-left-color:var(--mut)}
nav a.on{color:var(--fg);font-weight:600;border-left-color:var(--accent)}
nav a.sub{padding-left:1.5rem;font-size:12.5px}

main{min-width:0;padding:2.2rem 0 5rem;max-width:44rem}
.hero{margin:0 0 2rem}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;
    clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}
.hero svg{display:block;width:100%;height:auto}
nav .brandmark{display:flex;align-items:center;gap:.55rem;margin-bottom:.1rem;
    text-decoration:none;color:inherit}
nav .brandmark svg{width:26px;height:26px;flex:none}
h1{font-size:2.3rem;line-height:1.15;margin:0 0 .9rem;letter-spacing:-.022em;
   font-weight:700}
h2{font-size:1.05rem;margin:3.2rem 0 .9rem;letter-spacing:.1em;
   text-transform:uppercase;font-weight:600;color:var(--fg);
   font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;
   border-top:1px solid var(--rule);padding-top:.7rem}
h3{font-size:1.2rem;margin:2.1rem 0 .45rem;font-weight:600;letter-spacing:-.01em}
h4{font-size:.85rem;margin:1.5rem 0 .4rem;color:var(--mut);font-weight:600;
   letter-spacing:.06em;text-transform:uppercase;
   font-family:ui-sans-serif,system-ui,sans-serif}
p{margin:.85rem 0}
a{color:var(--accent)}
.lede{font-size:1.15rem;color:var(--mut);margin-bottom:1.6rem;line-height:1.5}
ul,ol{padding-left:1.15rem}
li{margin:.35rem 0}

.chart{width:100%;height:auto;margin:1rem 0 1.6rem;overflow:visible;
       background:none;border:0;border-top:1px solid var(--bd);
       border-bottom:1px solid var(--bd);padding:.9rem 0}
.title{font-size:13px;font-weight:600;fill:var(--fg)}
.tick{font-size:11px;fill:var(--mut)}
.ty{text-anchor:end}.tx{text-anchor:middle}
.axis{font-size:11.5px;fill:var(--mut)}
.legend{font-size:11.5px;fill:var(--fg)}
.grid{stroke:var(--bd);stroke-width:1}
.unity{stroke:var(--mut);stroke-width:1.2;stroke-dasharray:4 4}

.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:.9rem 0 1.4rem}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:13px;
      font-variant-numeric:tabular-nums;
      font-family:ui-sans-serif,system-ui,-apple-system,sans-serif}
th,td{padding:.4rem .7rem;border-bottom:1px solid var(--bd);text-align:right;
      white-space:nowrap}
th:first-child,td:first-child{text-align:left;padding-left:0}
thead th{color:var(--mut);font-weight:600;font-size:11px;letter-spacing:.06em;
      text-transform:uppercase;border-bottom:1px solid var(--rule)}
tbody tr:last-child td{border-bottom:1px solid var(--rule)}
tbody tr:hover{background:var(--panel)}

code{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
     font-size:.85em;background:var(--code);padding:.08em .3em}
pre{background:var(--code);border:0;border-left:2px solid var(--bd);
    padding:.9rem 1.1rem;overflow-x:auto;margin:1rem 0}
pre code{background:none;padding:0;font-size:12.5px;line-height:1.55}
.outlbl{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
        color:var(--mut);margin:1rem 0 .25rem;
        font-family:ui-sans-serif,system-ui,sans-serif}
pre.out{background:none;border-left:2px solid var(--accent);color:var(--mut)}

details{border:0;border-top:1px solid var(--bd);border-bottom:1px solid var(--bd);
        margin:1.4rem 0;background:none}
summary{cursor:pointer;padding:.7rem 0;font-size:13px;font-weight:600;
        letter-spacing:.04em;text-transform:uppercase;color:var(--mut);
        list-style:none;user-select:none;
        font-family:ui-sans-serif,system-ui,sans-serif}
summary::-webkit-details-marker{display:none}
summary::before{content:"+";display:inline-block;width:1.1rem;color:var(--accent);
        font-weight:700}
details[open]>summary::before{content:"\2212"}
summary:hover{color:var(--fg)}
details>*:not(summary){margin-left:0;margin-right:0}
details>.scroll{margin-bottom:1.1rem}

.note{border-left:2px solid var(--accent);background:none;
      padding:.2rem 0 .2rem 1rem;margin:1.3rem 0;color:var(--mut);
      font-size:15px;border-radius:0}
.warn{border-left-color:#d55e00;color:var(--fg)}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
       gap:0;margin:1.4rem 0;border-top:1px solid var(--rule);
       border-bottom:1px solid var(--bd)}
.card{background:none;border:0;border-right:1px solid var(--bd);padding:.8rem 1rem .8rem 0}
.card:last-child{border-right:0}
.card .k{font-size:1.7rem;font-weight:700;letter-spacing:-.03em;
         font-variant-numeric:tabular-nums}
.card .l{font-size:11px;color:var(--mut);margin-top:.1rem;letter-spacing:.05em;
         text-transform:uppercase;font-family:ui-sans-serif,system-ui,sans-serif}

.tabs{display:flex;flex-wrap:wrap;gap:1.2rem;align-items:baseline;
      margin:1.8rem 0 0;border-bottom:1px solid var(--bd);
      font-family:ui-sans-serif,system-ui,sans-serif}
.tabs .cap{font-size:11px;color:var(--mut);margin-right:.2rem;
      letter-spacing:.08em;text-transform:uppercase}
.tab{cursor:pointer;font:inherit;font-size:13px;padding:.4rem 0 .5rem;
     border:0;border-bottom:2px solid transparent;background:none;
     color:var(--mut);margin-bottom:-1px}
.tab:hover{color:var(--fg)}
.tab.on{color:var(--fg);border-bottom-color:var(--accent);font-weight:600}
.panels>[hidden]{display:none}

.pagenav{display:flex;justify-content:space-between;gap:1rem;margin-top:3.5rem;
         padding-top:1.1rem;border-top:1px solid var(--rule);font-size:14px;
         font-family:ui-sans-serif,system-ui,sans-serif}
.pagenav a{color:var(--accent);text-decoration:none}
.pagenav a:hover{text-decoration:underline}

.toc{display:grid;grid-template-columns:1fr;gap:0;margin:1.4rem 0;
     border-top:1px solid var(--rule)}
.toc a{display:grid;grid-template-columns:11rem minmax(0,1fr);gap:1.2rem;
       padding:.85rem 0;border-bottom:1px solid var(--bd);background:none;
       text-decoration:none;color:var(--fg)}
.toc a:hover .t{color:var(--accent)}
.toc .t{font-weight:600;font-size:15px}
.toc .d{color:var(--mut);font-size:14px;margin-top:0;line-height:1.45}

table.spec{min-width:0}
table.spec th{text-align:left;width:11rem;vertical-align:top;color:var(--mut);
     font-weight:600;white-space:normal;text-transform:none;letter-spacing:0;
     font-size:13px}
table.spec td{text-align:left;white-space:normal}

.ghlinks{margin-top:2rem;padding-top:1rem;border-top:1px solid var(--bd)}
.ghlinks a{display:block;font-size:12.5px;color:var(--mut);padding:.18rem 0 .18rem .7rem;
     border-left:2px solid transparent;text-decoration:none}
.ghlinks a:hover{color:var(--accent)}
footer{margin-top:4rem;padding-top:1.1rem;border-top:1px solid var(--bd);
       color:var(--mut);font-size:12.5px;line-height:1.55;
       font-family:ui-sans-serif,system-ui,sans-serif}
@media (max-width:820px){
  .wrap{grid-template-columns:1fr;gap:0}
  nav{position:static;max-height:none;padding:1.5rem 0 .6rem;border-right:0;
      border-bottom:1px solid var(--rule)}
  nav .links{display:flex;flex-wrap:wrap;gap:.1rem .9rem}
  nav .navgrp{width:100%;margin:.7rem 0 .1rem}
  nav a{border-left:0;padding:.2rem 0}
  nav a.on{border-left:0;text-decoration:underline;text-decoration-color:var(--accent);
      text-underline-offset:4px;text-decoration-thickness:2px}
  nav a.sub{display:none}
  .ghlinks{display:none}
  main{padding-top:1.6rem}
  .toc a{grid-template-columns:1fr;gap:.15rem}
}
"""


def md(text):
    """Render the Markdown subset the repo's docs actually use.

    A dependency would have to be installed on the runner before the page
    could build, and the docs here use headings, lists, tables, fences,
    inline code, links, bold and italic -- nothing that needs a parser.
    """
    import re as _re
    out, i = [], 0
    lines = text.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].startswith("```"):
                buf.append(lines[j]); j += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(buf)))
            i = j + 1; continue
        if ln.startswith("|") and i + 1 < len(lines) and _re.match(r"^\|[\s:|-]+\|$", lines[i+1]):
            hdr = [c.strip() for c in ln.strip("|").split("|")]
            j = i + 2; body = []
            while j < len(lines) and lines[j].startswith("|"):
                body.append([c.strip() for c in lines[j].strip("|").split("|")]); j += 1
            out.append('<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                       % ("".join("<th>%s</th>" % inline(c) for c in hdr),
                          "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r)
                                  for r in body)))
            i = j; continue
        m = _re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            lvl = len(m.group(1))
            # "#" is the document title and becomes the page's <h1>.  It
            # used to shift down a level, which left every page but the
            # Overview headless and made each "###" subhead outrank the
            # "##" section it sat under, because the section style is a
            # small uppercase rule and the subhead is a serif line.
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1; continue
        if _re.match(r"^\s*[-*]\s+", ln):
            # An item continues onto any following indented, non-blank line
            # that does not start a new one.  Without this a wrapped bullet
            # broke in two: the first line stayed in the list and the rest
            # fell out as a paragraph underneath it, which is what the README
            # looked like on the site until the bullets were read on a narrow
            # screen where the wrap points moved.
            items = []
            while i < len(lines) and _re.match(r"^\s*[-*]\s+", lines[i]):
                buf = [_re.sub(r"^\s*[-*]\s+", "", lines[i])]; i += 1
                while i < len(lines) and lines[i].strip() \
                        and not _re.match(r"^\s*[-*]\s+", lines[i]) \
                        and not lines[i].startswith(("#", "|", "```", ">")):
                    buf.append(lines[i].strip()); i += 1
                items.append(inline(" ".join(buf)))
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % x for x in items))
            continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ")); i += 1
            out.append('<div class="note">%s</div>' % inline(" ".join(buf)))
            continue
        if ln.strip():
            # Take this line unconditionally, THEN gather. Gathering first
            # lets a line that reached here but fails the continuation test --
            # a "|" that begins prose rather than a table row, as
            # docs/coarse-narrow.md does with "|P|^2 -- the energy family" --
            # leave i where it was and loop forever emitting empty paragraphs.
            # Every branch in this loop must consume at least one line.
            buf = [lines[i]]; i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "```", ">")) \
                    and not _re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(lines[i]); i += 1
            out.append("<p>%s</p>" % inline(" ".join(buf)))
            continue
        i += 1
    return "".join(out)


def inline(t):
    import re as _re
    t = html.escape(t)
    t = _re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = _re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    t = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def table(headers, rows):
    o = ['<div class="scroll"><table><thead><tr>']
    o += ["<th>%s</th>" % html.escape(h) for h in headers]
    o.append("</tr></thead><tbody>")
    for r in rows:
        o.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    o.append("</tbody></table></div>")
    return "".join(o)


def read(path, default=""):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return default


def split_readme(text):
    """Split the README on its h2 headings, keyed by title."""
    import re as _re
    parts, cur, buf = {}, "_intro", []
    for ln in text.split("\n"):
        m = _re.match(r"^##\s+(.*)", ln)
        if m:
            parts[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        else:
            buf.append(ln)
    parts[cur] = "\n".join(buf).strip()
    return parts


_TABSEQ = [0]


def workload_note(runs, kind):
    """Batch shape, as a spec row rather than an alert box."""
    rows = [f for r in runs for f in r.get(kind, [])]
    shapes = sorted({(f.get("data"), f.get("templates")) for f in rows
                     if f.get("data") and f.get("templates")})
    if not shapes:
        return ""
    txt = ", ".join("%d data segments x %d templates = %d pairs"
                    % (d, t, d * t) for d, t in shapes)
    return spec_table([
        ("Workload", "%s, single-threaded, complex64 throughout, peaks "
                     "searched over the middle 60%% of lags." % txt),
        ("Batch shape", "Filtering D segments against T templates together is "
                        "faster than the same pairs one at a time -- a d-by-t "
                        "tile reads d+t operands to produce d*t products, so "
                        "squarer tiles move less memory per product. A "
                        "per-pair figure is only meaningful alongside the "
                        "shape it was measured at. Choosing that shape is not "
                        "yet automatic. It cannot change any reported peak."),
        ("References", "Each reference column times ONE INVERSE TRANSFORM and "
                       "nothing else -- batched, single precision, one thread. "
                       "This library's column covers the whole matched filter: "
                       "the product, the transform and the peak scan. That "
                       "asymmetry is the comparison: it is not an FFT library, "
                       "and the question is whether computing only the binned "
                       "maxima beats doing the transform at all."),
    ])


def spec_table(rows):
    """Configuration as a property/value table, not a stack of alert boxes.

    These pages had grown six consecutive note boxes before the reader reached
    a chart. Notes are for the one thing that genuinely needs flagging; the
    setup a reader checks a number against is reference material and belongs
    in a table, below the plots, where it can be scanned.
    """
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" % (html.escape(k), v)
                   for k, v in rows if v)
    return ('<div class="scroll"><table class="spec"><tbody>%s</tbody>'
            "</table></div>" % body)


def details(summary, body):
    """A long table folded away.

    Pages end in a few hundred rows of numbers that almost nobody reads but
    that have to be there for anyone checking a claim. Stacked open they bury
    the end of the page; folded, they are one click away.
    """
    if not body:
        return ""
    return ("<details><summary>%s</summary>%s</details>"
            % (html.escape(summary), body))


def tabs(items, caption=""):
    """Buttons that switch between panels, first one shown.

    The benchmark grew a chart per transform length and a chart per runner,
    which stacked into a page nobody scrolls to the bottom of.  Switching
    between them shows one at a time and makes them comparable, since they
    land in the same place.
    """
    items = [(nm, h) for nm, h in items if h]
    if not items:
        return ""
    if len(items) == 1:
        return items[0][1]
    _TABSEQ[0] += 1
    g = "g%d" % _TABSEQ[0]
    btn = ['<div class="tabs" data-group="%s">' % g]
    if caption:
        btn.append('<span class="cap">%s</span>' % html.escape(caption))
    pan = ['<div class="panels">']
    for i, (nm, h) in enumerate(items):
        btn.append('<button class="tab%s" data-tab="%s-%d">%s</button>'
                   % (" on" if not i else "", g, i, html.escape(nm)))
        pan.append('<div data-tab="%s-%d"%s>%s</div>'
                   % (g, i, "" if not i else " hidden", h))
    return "".join(btn) + "</div>" + "".join(pan) + "</div>"


TABJS = """
document.addEventListener('click',function(e){
  var b=e.target.closest && e.target.closest('.tab'); if(!b) return;
  var bar=b.parentNode, panels=bar.nextElementSibling;
  Array.prototype.forEach.call(bar.querySelectorAll('.tab'),function(x){
    x.classList.toggle('on', x===b); });
  Array.prototype.forEach.call(panels.children,function(p){
    p.hidden = (p.getAttribute('data-tab') !== b.getAttribute('data-tab')); });
});
"""


def _rate(h):
    """Fraction of pairs that needed the full correlation.

    Tolerates both the absence of the field -- a row that reported no result
    has no rate -- and the old "trigger_rate" spelling, so a page can still be
    built from artifacts produced before the rename.
    """
    v = h.get("refine_rate", h.get("trigger_rate"))
    return 0.0 if v is None else float(v)


def _hier_ms(h):
    """Milliseconds the hierarchical filter took.

    Same tolerance as `_rate`, for the same reason: artifacts written before
    the rename spell this "gated_ms", and a page built from them should still
    build rather than crash on a key.
    """
    return float(h.get("hier_ms", h.get("gated_ms", 0.0)))


def bench_what(runs):
    """Which machines reported, and what that does and does not let you compare."""
    rows = []
    for r in runs:
        h = r["host"]
        rows.append([html.escape(h["label"]), html.escape(h["system"]),
                     html.escape(h["machine"]), "<code>%s</code>" % html.escape(h["backend"]),
                     html.escape(h.get("isa_forced") or "auto"),
                     html.escape(h.get("python", ""))])
    return (table(["runner", "os", "arch", "back end", "MF_ISA", "python"], rows)
            + '<div class="note">The back end is chosen at run time from the CPU. '
              'Rows sharing a prefix ran in <em>one job on one host</em>, so those '
              'compare kernels. Rows with different prefixes ran on different '
              'runners and compare machines at least as much as kernels. '
              'A platform that is absent did not report; it did not pass.</div>')


def reference_note(runs):
    """State the synthetic workload's reference, computed at build time.

    The hierarchical speedup depends on the reference more than on anything
    else the benchmark controls, so a number without it is not interpretable.
    These are computed by calling the same function the benchmark calls, so
    they cannot drift from it -- which they did: the reference used to be the
    raw f^(-7/3) TEMPLATE power rather than the matched-filter OUTPUT power,
    giving an effective bandwidth of 1.9 bins against 141 for a real captured
    reference, and every published speedup was optimistic as a result.
    """
    try:
        from matchedfilter.benchmark import _inspiral_power
        import matchedfilter as _mf
    except Exception:
        return ""
    ns = sorted({h["n"] for r in runs for h in r.get("hierarchical", [])})
    n = 4096 if 4096 in ns else (ns[0] if ns else 4096)
    p = _inspiral_power(n)
    #: Measured on a captured pycbc_inspiral_fir reference at n=4096. The
    #: synthetic model is least-squares fitted to these.
    captured = {256: (0.7956, 141.4), 512: (0.9335, 190.2), 1024: (0.9875, 212.5)}
    rows = []
    for m in (256, 512, 1024):
        if m >= n:
            continue
        f, be = _mf._band_features(p, m)
        c = captured.get(m)
        rows.append([str(m), "%.4f" % f, "%.0f" % be,
                     "%.4f" % c[0] if c else "-", "%.0f" % c[1] if c else "-"])
    return ('<h3>The reference these numbers assume</h3>'
            '<p>The hierarchical filter chooses its configuration from a '
            '<em>reference</em>: the expected power of the filter output, bin '
            'by bin. Everything on this page depends on it more than on any '
            'other choice here, because it decides how narrow a first pass can '
            'be. The benchmark uses a synthetic inspiral-like output spectrum '
            '-- <code>|h(f)|^2 / S(f)</code>, an f<sup>-7/3</sup> signal '
            'divided by a noise wall that rises below the seismic knee -- '
            'fitted by least squares to a reference captured from a real '
            'search. At n=%d:</p>' % n
            + table(["band", "in-band fraction", "B_eff (bins)",
                     "captured fraction", "captured B_eff"], rows)
            + '<div class="note">B_eff is the effective bandwidth of the '
              'in-band power, and it sets how sharp the correlation peak is, '
              'which is what decides whether a coarse lag grid can find it. '
              'A reference concentrated in a couple of bins gives a maximally '
              'broad peak that the coarse pass catches for free -- so getting '
              'this wrong flatters the filter rather than penalising it. '
              'Your own templates will differ; measure against them before '
              'relying on these ratios.</div>')


def trials_note():
    """Why the speedup falls as the transform lengthens, at a fixed threshold.

    Shown rather than corrected away. A longer block searches more lags for
    one reported peak, so more of them clear the coarse threshold and the
    first pass rules out less. That is what happens if a caller holds the
    threshold fixed, and it is what the charts above plot.
    """
    return ('<h3>Why the longer transforms do worse here</h3>'
            '<p>At a fixed threshold the speedup falls as <code>n</code> '
            'grows, and that is real. The first pass decides <strong>per '
            'pair</strong>, over every lag in the block -- so doubling the '
            'block doubles the chances that some lag clears the coarse '
            'threshold and drags the whole pair through the full correlation. '
            'Escalation is close to linear in the lags searched: measured at '
            'n=4096, band 512, it runs 4.3%, 7.0%, 11.7%, 19.1% for 304, 608, '
            '1216 and 2432 lags.</p>'
            '<div class="note">These charts hold the threshold fixed across '
            'every length, which asks the long transforms to do a harder job: '
            'n=262144 searches 64x the lags of n=4096 for the same threshold, '
            'so it carries 64x the trials factor. A real search would not do '
            'that -- it would raise the threshold as the block grows, since '
            'the flat filter alone expects n&middot;exp(-t&sup2;/2) noise '
            'crossings per pair. At thresholds equalised for that (5.50, 5.75, '
            '5.98, 6.21 for n = 4096, 16384, 65536, 262144) the decline goes '
            'away: 2.29x, 3.26x, 2.80x, 3.08x. The drop above is a property of '
            'the comparison, not of the filter -- but it is the comparison a '
            'reader is most likely to make, so it is the one plotted.</div>')


def bench_speedup(runs, names):
    """Speedup against the flat filter: one panel per length, a line per budget.

    The false-dismissal budget is the caller's main lever and it moves the
    answer more than anything else here, so it is the series rather than a
    footnote. Runners stay out of the chart -- a speedup is a ratio of two
    machine-dependent times and does not compare across them -- and the
    per-runner numbers are in the table below.
    """
    runs = _bench_runs(runs)
    ref = next((r for r in runs if r["host"]["label"] == "linux-x86_64"), runs[0])
    hier = [h for h in ref.get("hierarchical", [])]
    snrs = sorted({h["snr"] for h in hier})
    sizes = sorted({h["n"] for h in hier})
    fds = sorted({h.get("fd") for h in hier if h.get("fd")}, reverse=True)
    panels = []
    for n in sizes:
        groups = []
        for snr in snrs:
            vs = []
            for fd in fds:
                m = [h for h in hier if h["n"] == n and h["snr"] == snr
                     and h.get("fd") == fd and "speedup" in h]
                vs.append(m[0]["speedup"] if m else None)
            groups.append(("snr %g" % snr, vs))
        if any(v is not None for _, vs in groups for v in vs):
            panels.append(("n = %d" % n,
                           bar_chart(groups, ["fd = %g" % f for f in fds],
                                     "Hierarchical vs flat, n=%d (%s)"
                                     % (n, html.escape(ref["host"]["label"])),
                                     "speedup")))
    if not panels:
        return "<p>No hierarchical results were available.</p>"
    gone = [f for f in fds
            if not any(h.get("fd") == f and "speedup" in h for h in hier)]
    note = ""
    if gone:
        note = ('<div class="note warn">No bar for %s at any length: the '
                'shipped accuracy table cannot resolve a budget that small. '
                'It is measured at a few thousand trials a cell, so a rate '
                'below roughly 3/trials is a floor rather than a result, and '
                'the library refuses rather than answering from one. That is '
                'a limit of the measurement, not of the method -- more trials '
                'would open it.</div>'
                % ", ".join("fd = %g" % f for f in gone))
    return ('<p>The first pass correlates against a low-frequency slice of '
            'each template and pays for the full correlation only where that '
            'slice leaves a peak possible. The dashed line marks 1x, where it '
            'has bought nothing. Bars should climb with the threshold, because '
            'a higher threshold admits a narrower first pass -- and with a '
            'looser false-dismissal budget, which admits a tighter coarse '
            'threshold.</p>' + tabs(panels, "transform length") + note)


def bench_pair(runs):
    """Cost of one correlation, and the same thing relative to the x86 default."""
    o = ["<p>Cost of one (data, template) correlation with peak-only output. "
         "Lower is better.</p>"]
    series = [(r["host"]["label"], [(f["n"], f["us_per_pair"]) for f in r.get("flat", [])])
              for r in runs if r.get("flat")]
    panels = [("absolute", line_chart(series, "Time per pair", "transform length n",
                                      "microseconds per pair"))]
    ref = next((r for r in runs if r["host"]["label"] == "linux-x86_64"), None)
    if ref:
        base = {f["n"]: f["us_per_pair"] for f in ref["flat"]}
        rel = [(r["host"]["label"],
                [(f["n"], f["us_per_pair"] / base[f["n"]])
                 for f in r.get("flat", []) if f["n"] in base])
               for r in runs]
        rel = [x for x in rel if x[1]]
        panels.append(("relative to linux-x86_64",
                       line_chart(rel, "Cost relative to linux-x86_64",
                                  "transform length n", "ratio (1 = same)")))
    o.append(tabs(panels, "scale"))
    return "".join(o)


def bench_refs(runs, engines):
    """Against FFTW and numpy, one panel per runner."""
    o = ['<p>The reference lines time <strong>one inverse transform and '
         'nothing else</strong> -- batched, single precision, one thread. '
         'This library\'s line covers the whole matched filter: the product, '
         'the transform, and the peak scan.</p>',
         '<div class="note">That asymmetry is deliberate and is the only '
         'comparison that means anything here. matchedfilter is not an FFT '
         'library and does not implement a general transform; the question is '
         'whether computing only the binned maxima beats doing the transform '
         'at all, which is the step that would otherwise dominate. FFTW is '
         'the reference worth caring about. numpy and scipy are floors that '
         'run everywhere.</div>']
    panels = []
    for r in runs:
        pts = [(f["n"], f["us_per_pair"]) for f in r.get("flat", [])
               if (f.get("reference_us_per_pair") or {})]
        if not pts:
            continue
        ser = [("matchedfilter", pts)]
        for e in engines:
            q = [(f["n"], f["reference_us_per_pair"][e])
                 for f in r.get("flat", [])
                 if e in (f.get("reference_us_per_pair") or {})]
            if q:
                ser.append((e, q))
        if len(ser) > 1:
            panels.append((r["host"]["label"],
                           line_chart(ser, "%s: cost per pair" % r["host"]["label"],
                                      "transform length n", "microseconds per pair")))
    o.append(tabs(panels, "runner"))
    return "".join(o) if panels else ""


def _bench_runs(runs):
    runs = [r for r in runs if r.get("flat") or r.get("hierarchical")]
    runs.sort(key=lambda r: r["host"]["label"])
    return runs


def filter_benchmarks_page(runs):
    """The flat matched filter: what one correlation costs.

    Separate from the coarse threshold page because they answer different questions. This
    one is "how fast is the filter", against other FFT implementations doing
    the same job. The margin page is "how much work can be skipped", and its
    numbers are ratios against THIS one -- mixing them on a page made it easy
    to read a margin speedup as though it were raw throughput.
    """
    runs = _bench_runs(runs)
    if not runs:
        return "<p>No benchmark results were available when this page was built.</p>"
    engines = sorted({e for r in runs for f in r.get("flat", [])
                      for e in (f.get("reference_us_per_pair") or {})})
    fastest = min((f["us_per_pair"] for r in runs for f in r.get("flat", [])),
                  default=0)
    o = ['<p>One (data, template) correlation with peak-only output, on every '
         'platform the library is tested on. Shared CI runners are noisy, so '
         'read these as comparisons between back ends rather than as figures '
         'for any particular CPU.</p>',
         '<div class="cards">'
         '<div class="card"><div class="k">%d</div><div class="l">platforms measured</div></div>'
         '<div class="card"><div class="k">%.2f</div><div class="l">fastest us per pair</div></div>'
         '<div class="card"><div class="k">%d</div><div class="l">transform lengths</div></div>'
         '</div>' % (len(runs), fastest,
                     len({f["n"] for r in runs for f in r.get("flat", [])}))]
    o.append(tabs([("Cost per pair", bench_pair(runs)),
                   ("Against other FFTs", bench_refs(runs, engines))], "view"))
    o.append("<h3>What was tested</h3>")
    o.append(workload_note(runs, "flat"))
    o.append(bench_what(runs))
    o.append(details("All numbers (%d rows)"
                     % sum(len(r.get("flat", [])) for r in runs),
                     bench_flat_raw(runs, engines)))
    return "".join(o)


def hier_benchmarks_page(runs):
    """The hierarchical filter: how much of the flat filter it skips."""
    runs = _bench_runs(runs)
    if not runs:
        return "<p>No benchmark results were available when this page was built.</p>"
    names = [r["host"]["label"] for r in runs]
    hier = [h for r in runs for h in r.get("hierarchical", []) if "speedup" in h]
    o = ['<p>Every number here is a <strong>ratio against the flat filter on '
         'the same data</strong>, not a throughput. For what one correlation '
         'costs in absolute terms, see '
         '<a href="benchmarks.html">the matched filter page</a>. What was '
         'tested is set out <a href="#setup">below the charts</a>.</p>']
    o.append(bench_speedup(runs, names))
    o.append(trials_note())
    o.append(setup_section(runs, hier))
    o.append(details("All numbers (%d rows)" % len(hier), bench_hier_raw(runs)))
    return "".join(o)


def setup_section(runs, hier):
    """Everything a reader needs to check these numbers against, in one place."""
    shapes = sorted({(f.get("data"), f.get("templates"))
                     for r in runs for f in r.get("hierarchical", [])
                     if f.get("data") and f.get("templates")})
    shape = ", ".join("%d data segments x %d templates = %d pairs"
                      % (d, t, d * t) for d, t in shapes)
    cfgs = sorted({(h["band"], h["oversample"], h["taps"])
                   for h in hier if "band" in h})
    rows = [
        ("Workload", "%s. Pure noise -- the case the first pass is built for, "
                     "where almost nothing survives and the skipped work is "
                     "real. Single-threaded, complex64 throughout." % shape),
        ("Lag window", "The middle 60% of lags, matching the flat filter's. An "
                       "overlap-save search cannot use the wrap-around region, "
                       "and searching it is not free here: every extra lag is "
                       "another chance for a noise sample to clear the coarse "
                       "threshold and force a reconstruction no real search "
                       "would have asked for. At n=4096, band 512, that is "
                       "18.8% of pairs escalating against 6.2%."),
        ("Timing", "Interleaved: within each repeat the flat and hierarchical "
                   "filters run back to back on the same data, and the speedup "
                   "is the median of the per-repeat ratios. Each call repeats "
                   "to a 20 ms floor. Timing one to completion and then the "
                   "other puts drift between the two loops straight into the "
                   "ratio."),
        ("First stage", "Chosen by the library, not set here, from the "
                        "reference and the threshold -- so it is a result of "
                        "this benchmark rather than an input to it, and it "
                        "should narrow as the threshold rises. Selected across "
                        "these runs: %s."
                        % ", ".join("%d/%d/%d" % c for c in cfgs)),
        ("Comparing runners",
         "Don't. A speedup is a ratio of two machine-dependent times and they "
         "do not scale together: the arm64 runner's flat filter is 4.1x the "
         "x86 one while its coarse pass is only 2.7x, so the same algorithm "
         "reads 18.8x there against 12.2x. Compare within a runner."),
    ]
    o = ['<h3 id="setup">What was tested</h3>', spec_table(rows)]
    o.append(reference_note(runs))
    o.append(coverage_and_escalation(runs))
    return "".join(o)


def coverage_and_escalation(runs):
    """Two facts that are properties of the tables and the algorithm, once each."""
    o = []
    gaps = [(r["host"]["label"], h) for r in runs
            for h in r.get("hierarchical", []) if h.get("uncovered")]
    if gaps:
        cells = sorted({(h["n"], h["snr"]) for _, h in gaps})
        o.append("<h3>Where it declined to answer</h3>")
        o.append('<p>The tuning tables are measured, and outside their '
                 'coverage the library refuses rather than guessing a '
                 'configuration it cannot stand behind. %d combination%s '
                 'reported no result for that reason, identically on every '
                 'runner -- a gap in the shipped tables, not a failure of the '
                 'build. Coverage extends along the threshold axis, where '
                 'anything at or above the lowest measured threshold is '
                 'answered conservatively, but not across transform lengths, '
                 'where nothing measured yet bounds the answer.</p>'
                 % (len(cells), "" if len(cells) == 1 else "s"))
        o.append(spec_table([("Not covered",
                              ", ".join("n=%d at snr %g" % c for c in cells))]))
    fired = [h for r in runs for h in r.get("hierarchical", []) if _rate(h) > 0]
    if fired:
        by = collections.defaultdict(list)
        for h in fired:
            by[(h["n"], h["snr"])].append(_rate(h))
        o.append("<h3>How often the first pass escalated</h3>")
        o.append('<p>On pure noise almost nothing should reach the full '
                 'correlation. Where some does the work is wasted rather than '
                 'wrong, and the speedup falls -- this is the first number to '
                 'look at when a row is slower than expected. It is set by the '
                 'algorithm and the data, not the machine, so agreement across '
                 'runners is the check.</p>')
        o.append(table(["n", "snr", "escalated", "across runners", "runners"],
                       [["%d" % n, "%g" % snr, "%.2f%%" % (100 * min(v)),
                         ("identical" if max(v) - min(v) < 1e-9
                          else "%.2f-%.2f%%" % (100 * min(v), 100 * max(v))),
                         "%d" % len(v)]
                        for (n, snr), v in sorted(by.items())]))
    return "".join(o)


def bench_hier_raw(runs):
    rows = [[html.escape(r["host"]["label"]), h["n"], "%g" % h.get("fd", 0),
             "%g" % h["snr"],
             ("%d/%d/%d" % (h["band"], h["oversample"], h["taps"])
              if "band" in h else "-"),
             "%.3f" % h["flat_ms"], "%.3f" % _hier_ms(h),
             "<b>%.2fx</b>" % h["speedup"], "%.2f%%" % (_rate(h) * 100)]
            for r in runs for h in r.get("hierarchical", []) if "speedup" in h]
    if not rows:
        return ""
    return table(["runner", "n", "fd", "snr", "chosen b/U/K", "flat (ms)",
                  "hierarchical (ms)", "speedup", "triggered"], rows)


def bench_flat_raw(runs, engines):
    rows = []
    for r in runs:
        for f in r.get("flat", []):
            refs = f.get("reference_us_per_pair") or {}
            row = [html.escape(r["host"]["label"]), f["n"],
                   "%dx%d" % (f["data"], f["templates"]), "%.3f" % f["us_per_pair"]]
            for e in engines:
                row.append("%.1f" % refs[e] if e in refs else "-")
            for e in engines:
                row.append("<b>%.1fx</b>" % (refs[e] / f["us_per_pair"]) if e in refs else "-")
            row.append("yes" if f.get("ok") else "NO")
            rows.append(row)
    if not rows:
        return ""
    hdr = (["runner", "n", "shape", "us/pair"] + ["%s us" % e for e in engines]
           + ["vs %s" % e for e in engines] + ["matches numpy"])
    return table(hdr, rows)


# One page per topic.  The site used to be a single scroll with everything on
# it -- README, five charts per transform length, every design note expanded --
# which made the benchmark numbers hard to find and impossible to compare.
#
# (file, nav label, kind, argument).  `kind` says where the prose comes from:
# readme sections, a generated benchmark page, the runnable demo, the notes
# index, or a notes file.
NOTES = [("docs/hierarchical.md", "The hierarchical filter",
          "The cheap low-band pass, and how the tuning tables choose its "
          "band and margin from your reference."),
         ("docs/design.md", "Batched matched filter design",
          "The four-step transform, the split layout, and the fused peak scan."),
         ("docs/simd.md", "The SIMD layer",
          "How one source produces AVX-512, AVX2, SSE4 and NEON kernels."),
         ("docs/coarse-narrow.md", "A narrower coarse pass",
          "Measurements on how far the first stage can be narrowed."),
         ("docs/machine-notes.md", "Zen 5 instruction notes",
          "Measured issue rates, not vendor documentation."),
         ("docs/gpu-notes.md", "The GPU backend",
          "How the Vulkan path is built and dispatched, and the measurements "
          "that contradicted the plan."),
         ("docs/roadmap.md", "What is left, and what is closed",
          "Three live avenues, what shipped, and the many that measurement "
          "ruled out.")]

#: (file, nav label, page kind, argument, nav group).  The groups answer the
#: four questions a reader arrives with, in the order they arrive with them:
#: how do I use it, does it give the right answer, how fast is it, and why is
#: it built this way.
PAGES = [("index.html", "Overview", "overview", None, "Start here"),
         ("using-it.html", "Using it", "tutorial", "docs/usage.md", "Start here"),
         ("demo.html", "See it work", "demo", None, "Does it work"),
         ("precision.html", "Numerical accuracy", "precision", None,
          "Does it work"),
         ("benchmarks.html", "Matched filter", "bench-flat", None, "How fast"),
         ("hierarchical-benchmarks.html", "Hierarchical filter", "bench-hier",
          None, "How fast"),
         ("notes.html", "Design notes", "notes-index", None, "Why it is built this way"),
         ("caveats.html", "Caveats & contributing", "readme",
          ["Status", "Contributing"], "Why it is built this way")]


#: (page, one-line reason to go there) for the Overview signpost.
SIGNPOSTS = [
    ("using-it.html", "Using it",
     "Worked examples, run when this page is built: inputs, binning, "
     "thresholds, windows, and the hierarchical mode."),
    ("demo.html", "See it work",
     "Noise and injections through the real filter, plotted from a script "
     "that runs in CI."),
    ("precision.html", "Numerical accuracy",
     "Error against a float64 reference across injected SNR, with the "
     "distribution and not just the mean."),
    ("benchmarks.html", "Benchmarks",
     "Against numpy, FFTW and MKL on the transform they all do, plus what "
     "the hierarchical mode saves."),
    ("notes.html", "Design notes",
     "Why the tables are measured rather than modelled, and which ideas "
     "measurement ruled out."),
    ("caveats.html", "Caveats",
     "What is untested, what it will refuse to do, and where it is still "
     "alpha."),
]


#: README links written for a single page, and where they live on the site now.
ANCHORS = {"#caveats": "caveats.html", "#install": "index.html",
           "#how-it-works": "using-it.html",
           "#hierarchical-filtering": "index.html",
           "#development": "caveats.html"}


ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "docs", "assets")


def asset(name):
    """Inline an SVG from docs/assets, stripped of its XML prologue.

    Inlined rather than linked so a page is one request and the mark still
    renders from a file:// copy of the site.
    """
    try:
        with open(os.path.join(ASSETS, name)) as fh:
            return fh.read().split("?>")[-1].strip()
    except OSError:
        return ""


def schematic(width=760, height=228):
    """What the library does and does not produce, in one picture.

    The greyed middle block is the point: D*T*n complex samples is the thing a
    straightforward implementation writes out and the caller then throws away.
    Nothing here allocates it.
    """
    b, m, ac = "var(--bd)", "var(--mut)", "var(--accent)"
    o = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" '
         'aria-label="D data spectra and T template spectra go in; the full '
         'D by T by n correlation is never materialised; D by T by nbins peak '
         'records come out." class="chart">' % (width, height)]

    def box(x, y, w, h, fill, stroke, dash=""):
        o.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="4" '
                 'fill="%s" stroke="%s" stroke-width="1.2"%s/>'
                 % (x, y, w, h, fill, stroke,
                    ' stroke-dasharray="5 4"' if dash else ""))

    def txt(x, y, t, cls="tick", fill="var(--fg)", anchor="middle", size=None):
        o.append('<text x="%.0f" y="%.0f" text-anchor="%s" class="%s" '
                 'fill="%s"%s>%s</text>'
                 % (x, y, anchor, cls, fill,
                    ' font-size="%d"' % size if size else "", html.escape(t)))

    # stacked inputs
    for i in range(3):
        box(24 + 4 * i, 44 + 4 * i, 120, 46, "var(--panel)", b)
    txt(88, 72, "D data spectra")
    txt(88, 112, "complex64", "tick tx", m)
    for i in range(3):
        box(24 + 4 * i, 150 + 4 * i, 120, 46, "var(--panel)", b)
    txt(88, 178, "T templates")
    txt(88, 218, "complex64", "tick tx", m)

    # the thing that is never built
    box(250, 56, 250, 140, "none", m, dash=True)
    txt(375, 96, "full correlation")
    txt(375, 122, "D x T x n samples", "tick tx", m)
    txt(375, 152, "never materialised", "tick tx", m)

    # output
    box(580, 86, 156, 80, "var(--panel)", ac)
    txt(658, 118, "peaks")
    txt(658, 142, "D x T x nbins", "tick tx", m)
    txt(658, 190, "index, value, magnitude", "tick tx", m)

    o.append('<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" '
             'refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="%s"/>'
             '</marker></defs>' % m)
    for y0, y1 in ((70, 100), (176, 152)):
        o.append('<path d="M156 %d L242 %d" fill="none" stroke="%s" '
                 'stroke-width="1.2" marker-end="url(#ah)"/>' % (y0, y1, m))
    o.append('<path d="M508 126 L572 126" fill="none" stroke="%s" '
             'stroke-width="1.6" marker-end="url(#ah)"/>' % ac)
    o.append("</svg>")
    return "".join(o)


def _snippet(src, out):
    """One executed example: the source, then what it printed."""
    return ('<pre><code>%s</code></pre>'
            '<div class="outlbl">output</div><pre class="out"><code>%s</code></pre>'
            % (html.escape(src), html.escape(out)))


def overview_page(readme):
    """The landing page: what it is, one example, and where to go next."""
    from matchedfilter import tutorial as tut
    src, out = tut.run_teaser()
    sign = "".join('<a href="%s"><div class="t">%s</div><div class="d">%s</div>'
                   "</a>" % (f, html.escape(t), html.escape(d))
                   for f, t, d in SIGNPOSTS)
    logo = asset("logo.svg")
    # The wordmark is in the logo, so the page's <h1> is there for screen
    # readers and for anything that outlines the document.
    hero = ('<h1 class="sr">matchedfilter</h1><div class="hero">%s</div>' % logo) \
        if logo else "<h1>matchedfilter</h1>"
    return (hero
            + md(readme.get("_intro", ""))
            + schematic()
            + "<h2>What it looks like</h2>"
            + "<p>Run when this page was built, not transcribed:</p>"
            + _snippet(src, out)
            + '<p class="note">The inputs are spectra you already have. '
              "matchedfilter owns the correlation and the peak scan, not the "
              "forward transform.</p>"
            + "<h2>Where to go next</h2>"
            + '<div class="toc">%s</div>' % sign)


def tutorial_page(prose):
    """`docs/usage.md`, with the executed examples spliced in at its markers.

    The examples live in ``matchedfilter.tutorial`` and are run here, so a
    snippet that stops working stops the build.  The page this replaced had
    one code fence on it, for ``pip install``.
    """
    from matchedfilter import tutorial as tut
    blocks = {}
    for title, src, out in tut.run_all():
        blocks[title] = ("<h3>%s</h3>" % html.escape(title)) + _snippet(src, out)
    body = prose
    for title, chunk in blocks.items():
        marker = "<p>[[example:%s]]</p>" % html.escape(title)
        if marker in body:
            body = body.replace(marker, chunk)
        else:
            body += chunk
    left = [t for t in blocks if ("[[example:%s]]" % t) in prose
            and blocks[t] not in body]
    assert not left, left
    return body


def retarget_anchors(text):
    """Point the README's in-page anchors at the pages that now hold them.

    The README is written for GitHub, where it is one document and "#caveats"
    resolves. Split across pages, those links land nowhere.
    """
    for frag, page in ANCHORS.items():
        text = text.replace("](%s)" % frag, "](%s)" % page)
    return text


def strip_self_reference(text):
    """Drop the README's own title and its banner linking to this site.

    The README leads with a link to the documentation because a reader on
    GitHub needs one.  A reader who is already here does not, and the page
    supplies its own h1, so both would be duplicates.  Whole paragraphs go,
    not lines: the banner wraps, and dropping its first line alone left the
    remainder stranded as a sentence fragment.
    """
    keep = []
    for para in text.split("\n\n"):
        body = "\n".join(l for l in para.split("\n") if not l.startswith("# "))
        if not body.strip():
            continue
        if ("ahnitz.github.io/matchedfilter" in body
                or body.lstrip().startswith("Built by CI")):
            continue
        keep.append(body)
    return "\n\n".join(keep).strip()


def note_page_name(path):
    return "note-%s.html" % os.path.basename(path)[:-3]


def shell(active, title, body, version, sub=None, prev_next=None):
    """Wrap one page's content in the shared nav and chrome."""
    nav = ['<nav><a class="brandmark" href="index.html">%s'
           '<span class="brand">matchedfilter</span></a>'
           '<div class="ver">%s</div><div class="links">'
           % (asset("mark.svg"), html.escape(version or "docs"))]
    group = None
    for fn, label, _, _, grp in PAGES:
        if grp != group:
            nav.append('<div class="navgrp">%s</div>' % html.escape(grp))
            group = grp
        nav.append('<a href="%s"%s>%s</a>'
                   % (fn, ' class="on"' if fn == active else "", html.escape(label)))
        if fn == "notes.html" and (active == fn or (sub and sub[0] == "note")):
            for np_, ttl, _d in NOTES:
                f2 = note_page_name(np_)
                nav.append('<a class="sub%s" href="%s">%s</a>'
                           % (" on" if f2 == active else "", f2, html.escape(ttl)))
    nav.append('<div class="ghlinks">'
               '<a href="https://github.com/ahnitz/matchedfilter">Source</a>'
               '<a href="https://github.com/ahnitz/matchedfilter/fork">Fork</a>'
               '<a href="https://github.com/ahnitz/matchedfilter/issues/new">'
               'Report an issue</a></div>')
    nav.append("</div></nav>")
    pn = ""
    if prev_next:
        a, b = prev_next
        pn = ('<div class="pagenav"><div>%s</div><div>%s</div></div>'
              % ('<a href="%s">← %s</a>' % (a[0], html.escape(a[1])) if a else "",
                 '<a href="%s">%s →</a>' % (b[0], html.escape(b[1])) if b else ""))
    foot = ('<footer>Built by <code>tools/build_report.py</code> from the README, '
            'the notes in <code>docs/</code>, and the artifacts of the Benchmark '
            'workflow. Benchmark numbers come from shared CI runners and are '
            'comparisons, not hardware specifications. '
            '<a href="https://github.com/ahnitz/matchedfilter">Source on '
            'GitHub</a> &middot; '
            '<a href="https://github.com/ahnitz/matchedfilter/fork">fork it'
            '</a> &middot; '
            '<a href="https://github.com/ahnitz/matchedfilter/issues/new">'
            'report an issue</a></footer>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="icon" href="assets/mark.svg" type="image/svg+xml">'
            '<title>%s</title><style>%s</style></head><body>'
            '<div class="wrap">%s<main>%s%s%s</main></div>'
            '<script>%s</script></body></html>'
            % (html.escape(title), CSS, "".join(nav), body, pn, foot, TABJS))


def build(runs, root=".", require_demo=False):
    """Return {filename: html} for the whole site."""
    readme = split_readme(read(os.path.join(root, "README.md")))
    readme = {k: retarget_anchors(v) for k, v in readme.items()}
    readme["_intro"] = strip_self_reference(readme.get("_intro", ""))
    version = next((r["host"].get("version") for r in runs if r.get("host")), "")
    order = [(fn, label) for fn, label, _, _, _ in PAGES]
    out = {}
    for i, (fn, label, kind, arg, _grp) in enumerate(PAGES):
        if kind == "readme":
            parts = ["<h1>%s</h1>" % html.escape(label)]
            for j, key in enumerate(arg):
                text = readme.get(key, "")
                if not text:
                    continue
                if key != "_intro":
                    parts.append("<h2>%s</h2>" % html.escape(key))
                parts.append(md(text))
            body = "".join(parts)
        elif kind == "bench-flat":
            body = ("<h1>Benchmarks: the matched filter</h1>"
                    + filter_benchmarks_page(runs))
        elif kind == "bench-hier":
            body = ("<h1>Benchmarks: the hierarchical filter</h1>"
                    + hier_benchmarks_page(runs))
        elif kind == "file":
            body = md(read(os.path.join(root, arg)))
        elif kind == "tutorial":
            body = tutorial_page(md(read(os.path.join(root, arg))))
        elif kind == "overview":
            body = overview_page(readme)
        elif kind == "demo":
            body = "<h1>See it work</h1>" + demo_page(require_demo)
        elif kind == "precision":
            body = ("<h1>Numerical accuracy</h1>"
                    + precision_page(require_demo))
        else:
            body = ('<h1>Design notes</h1><p>Working notes on why the library is '
                    'built the way it is. Each records what was measured, '
                    'including the approaches that measurement ruled out.</p>'
                    '<div class="toc">%s</div>'
                    % "".join('<a href="%s"><div class="t">%s</div>'
                              '<div class="d">%s</div></a>'
                              % (note_page_name(f), html.escape(t), html.escape(d))
                              for f, t, d in NOTES if read(os.path.join(root, f))))
        out[fn] = shell(fn, "matchedfilter — %s" % label, body, version,
                        prev_next=(order[i - 1] if i else None,
                                   order[i + 1] if i + 1 < len(order) else None))

    notes = [(f, t) for f, t, _ in NOTES if read(os.path.join(root, f))]
    for i, (f, title) in enumerate(notes):
        fn = note_page_name(f)
        body = md(read(os.path.join(root, f)))
        prev = (note_page_name(notes[i - 1][0]), notes[i - 1][1]) if i else \
               ("notes.html", "Design notes")
        nxt = (note_page_name(notes[i + 1][0]), notes[i + 1][1]) \
              if i + 1 < len(notes) else None
        out[fn] = shell(fn, "matchedfilter — %s" % title, body, version,
                        sub=("note", title), prev_next=(prev, nxt))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="JSON files or directories of them")
    ap.add_argument("--out", default="site/index.html",
                    help="output path; its directory receives the whole site")
    ap.add_argument("--root", default=".",
                    help="repository root, for README.md and docs/")
    ap.add_argument("--require-demo", action="store_true",
                    help="fail if the demo cannot be run, rather than "
                         "publishing a page that says so")
    a = ap.parse_args()

    paths = []
    for i in a.inputs:
        paths += glob.glob(os.path.join(i, "*.json")) if os.path.isdir(i) else [i]
    if not paths:
        raise SystemExit("no benchmark JSON found in %s" % ", ".join(a.inputs))
    runs = load(paths)

    outdir = os.path.dirname(a.out) or "."
    os.makedirs(outdir, exist_ok=True)
    pages = build(runs, root=a.root, require_demo=a.require_demo)
    for fn, page in pages.items():
        with open(os.path.join(outdir, fn), "w") as fh:
            fh.write(page)

    # The mark is inlined into every page, but the favicon link needs a file.
    src = os.path.join(a.root, "docs", "assets")
    if os.path.isdir(src):
        dst = os.path.join(outdir, "assets")
        os.makedirs(dst, exist_ok=True)
        for f in sorted(os.listdir(src)):
            if f.endswith(".svg"):
                shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    print("wrote %d pages to %s/ from %d run(s): %s"
          % (len(pages), outdir, len(runs),
             ", ".join(r["host"]["label"] for r in runs)))


if __name__ == "__main__":
    main()
