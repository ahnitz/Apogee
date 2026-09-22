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


def test_site_pages_are_linked_and_complete():
    """Build the whole site from one synthetic run and check it hangs together."""
    run = {"host": {"label": "test-host", "system": "Linux", "machine": "x86_64",
                    "backend": "AVX3", "python": "3.12", "version": "0.0.0"},
           "flat": [{"n": 4096, "data": 8, "templates": 32, "us_per_pair": 1.0,
                     "ok": True, "reference_us_per_pair": {"numpy": 4.0}}],
           "hierarchical": [{"n": 4096, "snr": 5.0, "fd": 1e-3, "flat_ms": 2.0,
                             "gated_ms": 1.0, "speedup": 2.0, "trigger_rate": 0.0}]}
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
