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
:root{--fg:#1c1c1e;--mut:#6b6b70;--bd:#e0e0e4;--bg:#fff;--panel:#f7f7f9;
      --accent:#0072b2;--code:#f0f0f3}
@media (prefers-color-scheme:dark){:root{--fg:#e9e9ec;--mut:#9a9aa2;--bd:#32323a;
      --bg:#141417;--panel:#1c1c21;--accent:#4da3dd;--code:#1f1f25}}
:root[data-theme="light"]{--fg:#1c1c1e;--mut:#6b6b70;--bd:#e0e0e4;--bg:#fff;
      --panel:#f7f7f9;--accent:#0072b2;--code:#f0f0f3}
:root[data-theme="dark"]{--fg:#e9e9ec;--mut:#9a9aa2;--bd:#32323a;--bg:#141417;
      --panel:#1c1c21;--accent:#4da3dd;--code:#1f1f25}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:1rem}
body{margin:0;font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
     color:var(--fg);background:var(--bg)}
.wrap{display:grid;grid-template-columns:232px minmax(0,1fr);gap:2.5rem;
      max-width:1180px;margin:0 auto;padding:0 1.25rem}
nav{position:sticky;top:0;align-self:start;max-height:100vh;overflow-y:auto;
    padding:2rem 0 3rem}
nav .brand{font-weight:700;font-size:1.05rem;margin-bottom:.15rem}
nav .ver{color:var(--mut);font-size:12.5px;margin-bottom:1.25rem}
nav a{display:block;padding:.3rem .6rem;margin:.1rem 0;color:var(--mut);
      text-decoration:none;font-size:14px;border-radius:5px;border-left:2px solid transparent}
nav a:hover{color:var(--fg);background:var(--panel)}
nav a.sub{padding-left:1.4rem;font-size:13px}
main{min-width:0;padding:2rem 0 5rem}
h1{font-size:2rem;margin:0 0 .3rem;letter-spacing:-.02em}
h2{font-size:1.4rem;margin:3rem 0 .75rem;padding-bottom:.4rem;
   border-bottom:1px solid var(--bd);letter-spacing:-.01em}
h3{font-size:1.08rem;margin:1.9rem 0 .5rem}
h4{font-size:.95rem;margin:1.4rem 0 .4rem;color:var(--mut);font-weight:600}
p{margin:.7rem 0}
.lede{font-size:1.08rem;color:var(--mut);margin-bottom:1.5rem}
.chart{width:100%;height:auto;margin:.5rem 0 1.25rem;overflow:visible;
       background:var(--panel);border:1px solid var(--bd);border-radius:8px;padding:.4rem}
.title{font-size:14px;font-weight:600;fill:var(--fg)}
.tick{font-size:11px;fill:var(--mut)}
.ty{text-anchor:end}.tx{text-anchor:middle}
.axis{font-size:12px;fill:var(--mut)}
.legend{font-size:12px;fill:var(--fg)}
.grid{stroke:var(--bd);stroke-width:1;stroke-dasharray:2 3}
.unity{stroke:var(--mut);stroke-width:1.5;stroke-dasharray:5 4}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:.5rem 0 1rem}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px}
th,td{padding:.45rem .65rem;border-bottom:1px solid var(--bd);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{color:var(--mut);font-weight:600;border-bottom:2px solid var(--bd)}
tbody tr:hover{background:var(--panel)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;
     background:var(--code);padding:.12em .36em;border-radius:4px}
pre{background:var(--code);border:1px solid var(--bd);border-radius:8px;
    padding:.85rem 1rem;overflow-x:auto;margin:.8rem 0}
pre code{background:none;padding:0;font-size:13px;line-height:1.55}
details{border:1px solid var(--bd);border-radius:8px;margin:1rem 0;background:var(--panel)}
details[open]{background:transparent}
summary{cursor:pointer;padding:.7rem 1rem;font-size:14.5px;font-weight:600;
        list-style:none;user-select:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"\25B8";display:inline-block;margin-right:.55rem;
        color:var(--mut);transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}
summary:hover{color:var(--accent)}
details>*:not(summary){margin-left:1rem;margin-right:1rem}
details>.scroll{margin-bottom:1rem}
.note{border-left:3px solid var(--accent);background:var(--panel);
      padding:.7rem 1rem;margin:1.1rem 0;color:var(--mut);font-size:14.5px;
      border-radius:0 6px 6px 0}
.warn{border-left-color:#d55e00}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
       gap:.8rem;margin:1.2rem 0}
.card{background:var(--panel);border:1px solid var(--bd);border-radius:8px;padding:.8rem .9rem}
.card .k{font-size:1.5rem;font-weight:700;letter-spacing:-.02em}
.card .l{font-size:12.5px;color:var(--mut);margin-top:.15rem}
footer{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--bd);
       color:var(--mut);font-size:13px}
@media (max-width:820px){
  .wrap{grid-template-columns:1fr;gap:0}
  nav{position:static;max-height:none;padding:1.5rem 0 .5rem;
      border-bottom:1px solid var(--bd)}
  nav .links{display:flex;flex-wrap:wrap;gap:.2rem}
  nav a.sub{display:none}
  main{padding-top:1.5rem}
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
            out.append("<h%d>%s</h%d>" % (lvl + 1, inline(m.group(2)), lvl + 1))
            i += 1; continue
        if _re.match(r"^\s*[-*]\s+", ln):
            items = []
            while i < len(lines) and _re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(inline(_re.sub(r"^\s*[-*]\s+", "", lines[i]))); i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % x for x in items))
            continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ")); i += 1
            out.append('<div class="note">%s</div>' % inline(" ".join(buf)))
            continue
        if ln.strip():
            buf = []
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


def benchmarks_section(runs):
    """The benchmark part of the docs: charts first, raw numbers folded away."""
    runs = [r for r in runs if r.get("flat") or r.get("hierarchical")]
    runs.sort(key=lambda r: r["host"]["label"])
    if not runs:
        return "<p>No benchmark results were available when this page was built.</p>"
    names = [r["host"]["label"] for r in runs]
    o = []

    o.append("<p>Measured in CI on every platform the library is tested on. "
             "Shared runners are noisy, so these are comparisons between back "
             "ends rather than absolute figures for any particular CPU.</p>")

    best = max((h["speedup"] for r in runs for h in r.get("hierarchical", [])), default=0)
    o.append('<div class="cards">'
             '<div class="card"><div class="k">%d</div><div class="l">platforms measured</div></div>'
             '<div class="card"><div class="k">%.1fx</div><div class="l">best gate speedup</div></div>'
             '<div class="card"><div class="k">%d</div><div class="l">transform lengths</div></div>'
             '</div>' % (len(runs), best,
                         len({f["n"] for r in runs for f in r.get("flat", [])})))

    o.append("<h3>What was tested</h3>")
    rows = []
    for r in runs:
        h = r["host"]
        rows.append([html.escape(h["label"]), html.escape(h["system"]),
                     html.escape(h["machine"]), "<code>%s</code>" % html.escape(h["backend"]),
                     html.escape(h.get("isa_forced") or "auto"),
                     html.escape(h.get("python", ""))])
    o.append(table(["runner", "os", "arch", "back end", "MF_ISA", "python"], rows))
    o.append('<div class="note">The back end is chosen at run time from the CPU. '
             'Rows sharing a prefix ran in <em>one job on one host</em>, so those '
             'compare kernels. Rows with different prefixes ran on different '
             'runners and compare machines at least as much as kernels. '
             'A platform that is absent did not report; it did not pass.</div>')

    # ---------- hierarchical ----------
    o.append("<h3>Hierarchical gate</h3>")
    o.append("<p>The gate runs a cheap low-band pass first and pays for the full "
             "correlation only where a detection is still possible. Speedup is "
             "against the flat filter on the same data. The dashed line marks 1x, "
             "where gating has bought nothing.</p>")
    snrs = sorted({h["snr"] for r in runs for h in r.get("hierarchical", [])})
    sizes = sorted({h["n"] for r in runs for h in r.get("hierarchical", [])})
    for n in sizes:
        groups = []
        for snr in snrs:
            vs = []
            for r in runs:
                m = [h for h in r.get("hierarchical", []) if h["n"] == n and h["snr"] == snr]
                vs.append(m[0]["speedup"] if m else None)
            groups.append(("snr %g" % snr, vs))
        if any(v is not None for _, vs in groups for v in vs):
            o.append(bar_chart(groups, names, "Gated vs flat, n=%d" % n, "speedup"))

    fired = [(r["host"]["label"], h) for r in runs for h in r.get("hierarchical", [])
             if h["trigger_rate"] > 0]
    if fired:
        o.append('<div class="note warn"><strong>Where the gate opened on noise.</strong> '
                 'The gate should stay shut on pure noise; where it does not, the '
                 'work is wasted rather than wrong, and the speedup falls. This is '
                 'identical across every platform, so it is a property of the '
                 'calibration table rather than of any machine.</div>')
        o.append(table(["runner", "n", "snr", "speedup", "triggered"],
                       [[html.escape(l), h["n"], "%g" % h["snr"],
                         "%.2fx" % h["speedup"], "%.1f%%" % (h["trigger_rate"] * 100)]
                        for l, h in fired]))

    rows = [[html.escape(r["host"]["label"]), h["n"], "%g" % h["snr"],
             "%.3f" % h["flat_ms"], "%.3f" % h["gated_ms"],
             "<b>%.2fx</b>" % h["speedup"], "%.2f%%" % (h["trigger_rate"] * 100)]
            for r in runs for h in r.get("hierarchical", [])]
    if rows:
        o.append("<details><summary>All hierarchical results (%d rows)</summary>%s</details>"
                 % (len(rows), table(["runner", "n", "snr", "flat (ms)", "gated (ms)",
                                      "speedup", "triggered"], rows)))

    # ---------- flat ----------
    o.append("<h3>Matched filter, per pair</h3>")
    o.append("<p>Cost of one (data, template) correlation with peak-only output. "
             "Lower is better. numpy is included as a floor that runs everywhere, "
             "not as a competitive FFT.</p>")
    series = [(r["host"]["label"], [(f["n"], f["us_per_pair"]) for f in r.get("flat", [])])
              for r in runs if r.get("flat")]
    o.append(line_chart(series, "Time per pair", "transform length n",
                        "microseconds per pair"))

    ref = next((r for r in runs if r["host"]["label"] == "linux-x86_64"), None)
    if ref:
        base = {f["n"]: f["us_per_pair"] for f in ref["flat"]}
        rel = [(r["host"]["label"],
                [(f["n"], f["us_per_pair"] / base[f["n"]])
                 for f in r.get("flat", []) if f["n"] in base])
               for r in runs]
        rel = [x for x in rel if x[1]]
        o.append("<h4>Relative to the default x86 back end</h4>")
        o.append(line_chart(rel, "Cost relative to linux-x86_64",
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
        o.append("<details><summary>All matched-filter results (%d rows)</summary>%s</details>"
                 % (len(rows), table(["runner", "n", "shape", "us/pair",
                                      "numpy us/pair", "vs numpy", "matches numpy"], rows)))
    return "".join(o)


# Section id, sidebar label, and where the prose comes from.
SECTIONS = [
    ("overview",     "Overview",              ("readme", "_intro")),
    ("install",      "Install",               ("readme", "Install")),
    ("how",          "How it works",          ("readme", "How it works")),
    ("hierarchical", "Hierarchical filtering", ("readme", "Hierarchical filtering")),
    ("benchmarks",   "Benchmarks",            ("bench", None)),
    ("caveats",      "Caveats",               ("readme", "Caveats")),
    ("development",  "Development",           ("readme", "Development")),
    ("notes",        "Design notes",          ("notes", None)),
]

NOTE_FILES = [("docs/hierarchical.md", "The hierarchical filter"),
              ("docs/portable.md", "The portable back end"),
              ("docs/design.md", "Batched matched filter design")]


def build(runs, root="."):
    readme = split_readme(read(os.path.join(root, "README.md")))
    version = next((r["host"].get("version") for r in runs if r.get("host")), "")

    nav = ['<nav><div class="brand">matchedfilter</div>'
           '<div class="ver">%s</div><div class="links">' % html.escape(version or "docs")]
    body = []
    for sid, label, (src, key) in SECTIONS:
        if src == "readme":
            text = readme.get(key, "")
            if not text:
                continue
            content = md(text)
        elif src == "bench":
            content = benchmarks_section(runs)
        else:
            content = "".join(
                '<details><summary>%s</summary>%s</details>'
                % (html.escape(title), md(read(os.path.join(root, f))))
                for f, title in NOTE_FILES if read(os.path.join(root, f)))
            if not content:
                continue
        nav.append('<a href="#%s">%s</a>' % (sid, html.escape(label)))
        heading = "" if sid == "overview" else "<h2>%s</h2>" % html.escape(label)
        body.append('<section id="%s">%s%s</section>' % (sid, heading, content))
    nav.append("</div></nav>")

    head = ('<h1>matchedfilter</h1>'
            '<p class="lede">A fast single-threaded matched filter for x86, arm64 '
            'and macOS, with peak-only output and an optional hierarchical gate.</p>')
    foot = ('<footer>Built by <code>tools/build_report.py</code> from the README, '
            'the notes in <code>docs/</code>, and the artifacts of the Benchmark '
            'workflow. Benchmark numbers come from shared CI runners and are '
            'comparisons, not hardware specifications.</footer>')
    return '<div class="wrap">%s<main>%s%s%s</main></div>' % (
        "".join(nav), head, "".join(body), foot)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="JSON files or directories of them")
    ap.add_argument("--out", default="site/index.html")
    ap.add_argument("--root", default=".",
                    help="repository root, for README.md and docs/")
    a = ap.parse_args()

    paths = []
    for i in a.inputs:
        paths += glob.glob(os.path.join(i, "*.json")) if os.path.isdir(i) else [i]
    if not paths:
        raise SystemExit("no benchmark JSON found in %s" % ", ".join(a.inputs))
    runs = load(paths)

    body = build(runs, root=a.root)
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>matchedfilter</title><style>%s</style></head>"
            "<body>%s</body></html>" % (CSS, body))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(page)
    print("wrote %s from %d run(s): %s"
          % (a.out, len(runs), ", ".join(r["host"]["label"] for r in runs)))


if __name__ == "__main__":
    main()
