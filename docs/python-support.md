# Python version support

As of 2026-09-26, the minimum supported Python version is 3.10. Python 3.9
support was dropped by project decision after its CI test job failed; the
failure was reproduced in `test_metal_ownership.py`. Its reference-count
assertion compares a `Counter` containing a zero-count entry with one that
omits the entry. Python 3.9 considers these unequal; Python 3.10 and newer
consider them equal. This was a test compatibility issue, not a filtering or
GPU ownership defect. The Python 3.11–3.14 jobs passed on commit f48a32e.

Package metadata requires Python >=3.10, release wheels cover CPython
3.10–3.14, and the CI matrix tests each of those versions. Python 3.10
replaces 3.9 as the oldest supported CI target. Historical test reports retain
the versions they actually tested.
