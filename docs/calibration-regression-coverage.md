# Calibration and optimization regression coverage

## Standard execution

Ordinary `python -m pytest` discovers `test_coarse_fdr.py`; there is no slow
marker, environment opt-in or separate tuning command. Its independent
NumPy-vs-native CPU comparison runs even without a GPU and is therefore
included in the CI Python/CPU-target matrix and installed-wheel tests.
NumPy FFTs here are independent test oracles, not package execution paths.

GPU comparisons also run whenever hardware is available. The macOS GPU job
is now required (no `continue-on-error`) and uses `--require-coarse-gpu`.
That option makes missing hardware, failed probing or unsupported coarse
matrix sizes fail rather than silently skip the calibration check. It can
also be used on a Radeon/Vulkan runner. CPU-only developer machines still
skip GPU comparisons honestly; a test cannot execute absent hardware.
The existing hosted workflow supplies Metal coverage, not Radeon hardware.

## Added assumptions

- Native CPU coarse numerical behavior is compared with an independent
  complex128 FFT oracle at both empirical FDR tails. Previously, CPU and GPU
  could drift together, and all numerical transfer cases skipped without GPU.
- Production hierarchical admission must match an independently normalized
  coarse FFT, with both survivors and dismissals. This covers reference power
  fraction, the coarse FFT scale, and threshold application, which a direct
  kernel comparison alone bypasses.
- Reordering and unevenly partitioning a bank must preserve admission and
  peak values, including changes from packed/tiled dispatch to fallback.
- Reciprocal data/template scaling preserves correlation and admission;
  reference amplitude scaling preserves its dimensionless power fraction.
- Updating a reference after execution must refresh resident coarse template
  normalization, not only the Python selection metadata.
- Timing/cost data cannot alter a calibrated threshold for a fixed reference
  and configuration.
- Shipped THR rows must be finite, physically valid, nonempty and unique
  after the loader's SNR normalization. Duplicate cells otherwise make
  interpolation ambiguous and can overweight a measurement.

The end-to-end tests use an intentional gap around the threshold, so they
catch normalization/dispatch mistakes without failing on expected fp16
rounding. The statistical transfer tests separately exercise tail decisions.

## Existing guards and remaining limits

Existing tests already exercise missing-calibration refusal, series FFT
normalization, shared-buffer/cache lifetime, peak/index consistency, shipped
kernel freshness, size/geometry support, selection monotonicity, and signal
versus noise populations. These are complementary to the new checks.

Remaining limits are explicit: the quick transfer sweep covers coarse sizes
64–2048 and a small spectral family; larger sizes and independent held-out
validation of actual table rows require broader tests. Empirical CPU quantiles
are a drift detector, not certification of population FDR. The old CPU
zero/equality coarse-gate boundary finding in `execution-audit.md` also remains
open; these positive, separated-threshold tests do not claim to fix it.

## Validation

On Radeon 8060S, `python -m pytest -q tests --require-coarse-gpu` completed
with **793 passed, 10 skipped**. A forced no-GPU probe correctly failed the
required mode rather than skipping. Linux hosted CI does not use that flag;
only the Apple hardware job requires GPU execution.
