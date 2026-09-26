"""The documentation builder, which has hung the CI page job once.

These are cheap and they guard failures that are invisible until the page is
built: a renderer that never terminates, and a site whose pages do not link to
each other.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

build_report = pytest.importorskip("build_report")


@pytest.mark.parametrize("line", [
    "|P|^2 -- the energy family, and nothing beats it",   # the real one
    "| not a table either",
    "|",
])
def test_pipe_prose_terminates(line):
    """A line starting with "|" that is not a table must not loop forever.

    docs/coarse-narrow.md wraps a paragraph so that "|P|^2 -- the energy
    family" begins a line.  The table branch declined it, no other branch
    claimed it, and the paragraph branch gathered zero lines and left the
    cursor where it was, emitting empty paragraphs until the builder died at
    4 GB.  Every branch has to consume at least one line.
    """
    out = build_report.md("Before.\n\n%s\n\nAfter." % line)
    assert "Before." in out and "After." in out
    assert out.count("<p></p>") == 0


def test_every_shipped_doc_renders():
    """Each docs/*.md must render, since the site now gives each its own page."""
    d = os.path.join(ROOT, "docs")
    names = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    assert names, "no docs to render"
    for name in names:
        with open(os.path.join(d, name)) as fh:
            assert build_report.md(fh.read()).strip(), name


def test_tables_still_render():
    """The pipe fix must not cost us real tables."""
    out = build_report.md("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in out and "<th>a</th>" in out and "<td>2</td>" in out


def test_wrapped_list_items_stay_in_the_list():
    """A bullet that wraps is one item, not an item plus a paragraph.

    Every bullet in the README wraps.  Rendered without this the second line
    of each fell out of the <ul> as its own paragraph, which read as prose
    interleaved between the bullets.
    """
    out = build_report.md("- **A.** one\n  two three\n- **B.** four\n\nafter\n")
    assert out.count("<li>") == 2
    assert "<li><strong>A.</strong> one two three</li>" in out
    assert out.endswith("<p>after</p>")
    # a wrapped item must not swallow what comes after the list
    assert "<p>after</p>" not in out[:out.index("</ul>")]


def test_pre_rename_hier_ms_spelling():
    """Artifacts written before the rename spell the time "gated_ms"."""
    assert build_report._hier_ms({"gated_ms": 1.5}) == 1.5
    assert build_report._hier_ms({"hier_ms": 2.5}) == 2.5


def test_examples_on_the_using_it_page_are_executed():
    """Every marker in docs/usage.md is filled by a real run.

    The snippets are run at build time precisely so they cannot drift; if a
    marker survives into the HTML, one silently did not run.
    """
    with open(os.path.join(ROOT, "docs", "usage.md")) as fh:
        prose = fh.read()
    page = build_report.tutorial_page(build_report.md(prose))
    assert "[[example:" not in page
    assert page.count('class="outlbl"') >= 8


def test_site_pages_are_linked_and_complete():
    """Build the whole site from one synthetic run and check it hangs together."""
    run = {"host": {"label": "test-host", "system": "Linux", "machine": "x86_64",
                    "backend": "AVX3", "python": "3.12", "version": "0.0.0"},
           "flat": [{"n": 4096, "data": 8, "templates": 32, "us_per_pair": 1.0,
                     "ok": True, "reference_us_per_pair": {"numpy": 4.0}}],
           "hierarchical": [
               {"n": 4096, "snr": 5.0, "fd": 1e-3, "flat_ms": 2.0,
                "hier_ms": 1.0, "speedup": 2.0, "refine_rate": 0.0,
                "band": 1024, "taps": 8},
               # a row that escalated, so the "where it fired" table renders
               {"n": 4096, "snr": 5.5, "fd": 1e-3, "flat_ms": 2.0,
                "hier_ms": 1.5, "speedup": 1.33, "refine_rate": 0.12,
                "band": 512, "taps": 8},
               # and one the tables did not cover, which carries NO speedup
               # and NO rate at all. This shape crashed the CI page build.
               {"n": 16384, "snr": 6.5, "fd": 1e-3, "uncovered": "not tuned"}]}
    pages = build_report.build([run], root=ROOT)
    assert "index.html" in pages and "benchmarks.html" in pages
    for name, html_text in pages.items():
        assert html_text.startswith("<!doctype html>"), name
        assert "</html>" in html_text, name
    # every internal href resolves to a page that was actually generated
    import re
    for name, html_text in pages.items():
        for href in re.findall(r'href="([^"#:]+\.html)"', html_text):
            assert href in pages, "%s links to missing %s" % (name, href)


def test_readme_keeps_the_docs_link_but_the_site_does_not_repeat_it():
    """The link belongs at the top on GitHub and nowhere on the site itself."""
    with open(os.path.join(ROOT, "README.md")) as fh:
        readme = fh.read()
    assert "ahnitz.github.io/matchedfilter" in readme[:400]
    stripped = build_report.strip_self_reference(
        build_report.split_readme(readme)["_intro"])
    assert "ahnitz.github.io" not in stripped
    assert not stripped.startswith("#")
    assert "Built by CI" not in stripped


def test_page_builds_from_pre_rename_artifacts():
    """Old artifacts say "trigger_rate"; the page must still build.

    Benchmark JSON is uploaded by one CI job and consumed by another, and a
    rerun of the page job can pick up artifacts produced before a rename.
    """
    run = {"host": {"label": "old-host", "system": "Linux", "machine": "x86_64",
                    "backend": "AVX2", "python": "3.12", "version": "0.0.0"},
           "flat": [{"n": 4096, "data": 8, "templates": 32, "us_per_pair": 1.0,
                     "ok": True}],
           "hierarchical": [{"n": 4096, "snr": 5.0, "fd": 1e-3, "flat_ms": 2.0,
                             "hier_ms": 1.0, "speedup": 2.0,
                             "trigger_rate": 0.2}]}
    pages = build_report.build([run], root=ROOT)
    # the escalation table now reports one row per (n, snr), deduplicated
    # across runners, so look for the rate rather than a runner name
    assert "20.00%" in pages["hierarchical-benchmarks.html"]


def test_readme_banner_renders_once_with_working_image_paths():
    from html.parser import HTMLParser
    class Images(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []
        def handle_starttag(self, tag, attrs):
            if tag == 'img':
                self.sources.append(dict(attrs).get('src'))
    with open(os.path.join(ROOT, 'README.md')) as stream:
        intro = build_report.split_readme(stream.read())['_intro']
    intro = build_report.strip_self_reference(build_report.retarget_anchors(intro))
    page = build_report.overview_page({'_intro': intro})
    parser = Images()
    parser.feed(page)
    assert parser.sources.count('assets/teaser.svg') == 1
    assert 'docs/assets/teaser.svg' not in page
    assert '&lt;p align=' not in page
    assert '<strong>Batched matched filtering' in page
    assert '537 MB' in page


def test_historical_benchmark_artifacts_use_representative_targets():
    def run(label, backend):
        return {'host': {'label': label, 'backend': backend, 'system': 'test', 'machine': 'test'},
                'flat': [{'n': 1024, 'data': 1, 'templates': 1, 'us_per_pair': 1.,
                          'ok': True, 'reference_us_per_pair':
                          {'numpy': 2., 'scipy': 2., 'fftw': 3., 'mkl': 4.}}]}
    runs = [run('linux-x86_64', 'AVX3'), run('linux-x86_64-AVX3', 'AVX3'),
            run('linux-x86_64-AVX2', 'AVX2'), run('linux-x86_64-SSE4', 'SSE4'),
            run('macos-arm64', 'NEON_BF16'), run('macos-arm64-NEON', 'NEON'),
            run('macos-arm64-NEON_WITHOUT_AES', 'NEON_WITHOUT_AES'),
            run('my-custom-host-name', 'AVX2'), run('my-custom-host-name-AVX2', 'AVX2')]
    picked = build_report._bench_runs(runs)
    assert [r['host']['label'] for r in picked] == [
        'linux-x86_64', 'linux-x86_64-AVX2', 'macos-arm64', 'my-custom-host-name']
    page = build_report.filter_benchmarks_page(runs)
    assert 'NEON_WITHOUT_AES' not in page and 'linux-x86_64-AVX3' not in page
    assert '<th>numpy us</th>' not in page and '<th>scipy us</th>' not in page
    assert '<th>fftw us</th>' in page and '<th>mkl us</th>' in page


def test_readme_horizontal_rules_are_not_literal_dashes():
    assert build_report.md("before\n\n---\n\nafter") == "<p>before</p><hr><p>after</p>"
