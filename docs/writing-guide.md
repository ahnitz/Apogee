# Documentation editing checklist

Keep the README useful to someone installing the library for the first time.
Put a runnable example before benchmark claims. Use the usage guide for the
current API and design notes for experiments and implementation history.

Before publishing:

- Check supported sizes, device behavior and calibration requirements against
  the current API. Transform support does not imply calibration coverage.
- Run examples. State array shapes, normalization and output lifetime where
  the reader needs them.
- For timings, name the hardware, batch shape, transform length, timed API,
  units and excluded work. Distinguish kernel timing from a public API call.
- Describe measured results as observations on that workload. Do not promise
  speedups across hardware or imply that different workloads are equivalent.
- Keep all available transform sizes in the existing benchmark pages. Label
  missing measurements and calibration gaps explicitly.
- Use descriptive, sentence-case headings and short paragraphs. Remove hype,
  rhetorical questions, repeated conclusions and claims such as “the only
  comparison that matters.” Prefer the concrete behavior and its limits.
- Preserve useful historical notes, but mark them as history when behavior has
  changed. Link readers to current instructions.
- Check light and dark themes, keyboard focus, narrow screens, code overflow,
  chart labels and internal links. Color must not be the only series label.

The website takes its quick start from the README. Usage examples execute
while building the site. Run `pytest tests/test_docs.py` after editing either.

References: [Diátaxis](https://diataxis.fr/start-here/),
[Google's tone guide](https://developers.google.com/style/tone),
[Microsoft's concise-writing guide](https://learn.microsoft.com/en-us/style-guide/word-choice/use-simple-words-concise-sentences),
and [Google's accessibility guide](https://developers.google.com/style/accessibility).
