#!/usr/bin/env python3
"""Combine benchmark JSON from several machines into one page.

    python tools/build_report.py results/ --out site/index.html

Charts are inline SVG.  No JavaScript and no external assets, so the page
renders from a file:// URL, inside a PR comment, or on GitHub Pages without
anything else being fetched.
"""
import argparse
import glob
import html
import json
import os

# Colour-blind-safe, and distinguishable in greyscale by order.
PALETTE = ["#0072b2", "#d55e00", "#009e73", "#cc79a7", "#e69f00", "#56b4e9",
           "#8c564b", "#333333"]


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
    if v >= 100:
        return "%.0f" % v
    if v >= 10:
        return "%.0f" % v
    if v >= 1:
        return "%.1f" % v
    return "%.2f" % v


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
:root{--fg:#1a1a1a;--mut:#666;--bd:#d8d8d8;--bg:#fff;--accent:#0072b2}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e8;--mut:#a0a0a0;--bd:#3a3a3a;--bg:#161616}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem 4rem;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg)}
main{max-width:860px;margin:0 auto}
h1{font-size:1.9rem;margin:0 0 .25rem}
h2{font-size:1.25rem;margin:2.5rem 0 .5rem;padding-bottom:.3rem;border-bottom:1px solid var(--bd)}
h3{font-size:1rem;margin:1.6rem 0 .4rem;color:var(--mut);font-weight:600}
p{margin:.6rem 0}
.sub{color:var(--mut);margin-bottom:1.5rem}
.chart{width:100%;height:auto;margin:.5rem 0 1rem;overflow:visible}
.title{font-size:14px;font-weight:600;fill:var(--fg)}
.tick{font-size:11px;fill:var(--mut)}
.ty{text-anchor:end}.tx{text-anchor:middle}
.axis{font-size:12px;fill:var(--mut)}
.legend{font-size:12px;fill:var(--fg)}
.grid{stroke:var(--bd);stroke-width:1;stroke-dasharray:2 3}
.unity{stroke:var(--mut);stroke-width:1.5;stroke-dasharray:5 4}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px}
th,td{padding:.45rem .6rem;border-bottom:1px solid var(--bd);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:rgba(128,128,128,.14);padding:.1em .35em;border-radius:3px}
.note{border-left:3px solid var(--accent);padding:.5rem .9rem;margin:1rem 0;color:var(--mut);font-size:14.5px}
footer{margin-top:3rem;color:var(--mut);font-size:13px}
"""


def table(headers, rows):
    o = ['<div class="scroll"><table><thead><tr>']
    o += ["<th>%s</th>" % html.escape(h) for h in headers]
    o.append("</tr></thead><tbody>")
    for r in rows:
        o.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    o.append("</tbody></table></div>")
    return "".join(o)


def build(runs):
    runs = [r for r in runs if r.get("flat") or r.get("hierarchical")]
    runs.sort(key=lambda r: r["host"]["label"])
    names = [r["host"]["label"] for r in runs]

    o = ['<main>']
    o.append("<h1>matchedfilter benchmarks</h1>")
    o.append('<p class="sub">Measured in CI across every platform the library '
             'supports. Shared runners are noisy, so read these as comparisons '
             'between back ends, not as absolute hardware figures.</p>')

    # ---- what was tested ----
    o.append("<h2>What was tested</h2>")
    rows = []
    for r in runs:
        h = r["host"]
        rows.append([html.escape(h["label"]), html.escape(h["system"]),
                     html.escape(h["machine"]), "<code>%s</code>" % html.escape(h["backend"]),
                     html.escape(h.get("isa_forced") or "auto"),
                     html.escape(h.get("version", "")), html.escape(h.get("python", ""))])
    o.append(table(["runner", "os", "arch", "back end", "MF_ISA", "version", "python"], rows))
    o.append('<div class="note">The back end is chosen at run time from the CPU. '
             'The three <code>linux-x86_64*</code> rows are the same machine forced '
             'down different kernels, so they isolate the back end from the hardware.</div>')

    # ---- hierarchical: the point of the package ----
    o.append("<h2>Hierarchical gate</h2>")
    o.append("<p>The gate runs a cheap low-band pass first and pays for the full "
             "correlation only where a detection is still possible. Speedup is "
             "against the flat filter on the same data; the dashed line is 1x, "
             "where gating has bought nothing.</p>")
    snrs, sizes = set(), set()
    for r in runs:
        for h in r.get("hierarchical", []):
            snrs.add(h["snr"]); sizes.add(h["n"])
    snrs, sizes = sorted(snrs), sorted(sizes)

    for n in sizes:
        groups = []
        for snr in snrs:
            vs = []
            for r in runs:
                m = [h for h in r.get("hierarchical", []) if h["n"] == n and h["snr"] == snr]
                vs.append(m[0]["speedup"] if m else None)
            groups.append(("snr %g" % snr, vs))
        if any(v is not None for _, vs in groups for v in vs):
            o.append("<h3>n = %d</h3>" % n)
            o.append(bar_chart(groups, names,
                               "Gated vs flat, n=%d" % n, "speedup"))

    rows = []
    for r in runs:
        for h in r.get("hierarchical", []):
            rows.append([html.escape(r["host"]["label"]), h["n"], "%g" % h["snr"],
                         "%.3f" % h["flat_ms"], "%.3f" % h["gated_ms"],
                         "<b>%.2fx</b>" % h["speedup"], "%.2f%%" % (h["trigger_rate"] * 100)])
    if rows:
        o.append("<h3>All hierarchical results</h3>")
        o.append(table(["runner", "n", "snr", "flat (ms)", "gated (ms)",
                        "speedup", "triggered"], rows))

    # ---- flat filter across platforms ----
    o.append("<h2>Matched filter, per pair</h2>")
    o.append("<p>Cost of one (data, template) correlation with peak-only output. "
             "Lower is better. This is where the portable back end is compared "
             "against the hand-written x86 kernels.</p>")
    series = []
    for r in runs:
        pts = [(f["n"], f["us_per_pair"]) for f in r.get("flat", [])]
        if pts:
            series.append((r["host"]["label"], pts))
    o.append(line_chart(series, "Time per pair", "transform length n",
                        "microseconds per pair"))

    ref = next((r for r in runs if r["host"]["label"] == "linux-x86_64"), None)
    if ref:
        base = {f["n"]: f["us_per_pair"] for f in ref["flat"]}
        rel = []
        for r in runs:
            pts = [(f["n"], f["us_per_pair"] / base[f["n"]])
                   for f in r.get("flat", []) if f["n"] in base]
            if pts:
                rel.append((r["host"]["label"], pts))
        o.append("<h3>Relative to linux-x86_64</h3>")
        o.append(line_chart(rel, "Cost relative to the default x86 back end",
                            "transform length n", "ratio (1 = same)"))

    rows = []
    for r in runs:
        for f in r.get("flat", []):
            sp = ("%.1fx" % (f["numpy_us_per_pair"] / f["us_per_pair"])
                  if f.get("numpy_us_per_pair") else "-")
            rows.append([html.escape(r["host"]["label"]), f["n"],
                         "%dx%d" % (f["data"], f["templates"]),
                         "%.3f" % f["us_per_pair"],
                         "%.2f" % f["numpy_us_per_pair"] if f.get("numpy_us_per_pair") else "-",
                         sp, "yes" if f.get("ok") else "NO"])
    if rows:
        o.append("<h3>All matched-filter results</h3>")
        o.append(table(["runner", "n", "shape", "us/pair", "numpy us/pair",
                        "vs numpy", "matches numpy"], rows))

    o.append('<footer>Generated by <code>tools/build_report.py</code> from the '
             'artifacts of the Benchmark workflow. numpy is included as a floor '
             'that runs everywhere, not as a competitive FFT.</footer>')
    o.append("</main>")
    return "".join(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="JSON files or directories of them")
    ap.add_argument("--out", default="site/index.html")
    a = ap.parse_args()

    paths = []
    for i in a.inputs:
        paths += glob.glob(os.path.join(i, "*.json")) if os.path.isdir(i) else [i]
    if not paths:
        raise SystemExit("no benchmark JSON found in %s" % ", ".join(a.inputs))
    runs = load(paths)

    body = build(runs)
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>matchedfilter benchmarks</title><style>%s</style></head>"
            "<body>%s</body></html>" % (CSS, body))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(page)
    print("wrote %s from %d run(s): %s"
          % (a.out, len(runs), ", ".join(r["host"]["label"] for r in runs)))


if __name__ == "__main__":
    main()
