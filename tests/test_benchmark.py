"""Exercise CLI reporting without expensive timing or optional FFT engines."""
import json

from matchedfilter import benchmark


def test_hierarchical_cli_reports_two_field_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(benchmark, "_one",
                        lambda *args: (1.0, {}, "indices match", None))
    monkeypatch.setattr(benchmark, "FD_SWEEP", (1e-3,))
    monkeypatch.setattr(benchmark, "_plan_seconds", {})

    def bench_hier(n, nd, nt, snr, fd, reps):
        if snr == 5.0:
            raise ValueError("uncovered calibration")
        return .002, .001, .25, (128, 4), 2.0

    monkeypatch.setattr(benchmark, "_bench_hier", bench_hier)
    output = tmp_path / "benchmark.json"
    assert benchmark.main(["--n", "1024", "--data", "1", "--templates", "1",
                           "--reps", "1", "--json", str(output)]) == 0
    stdout = capsys.readouterr().out
    assert "128/4" in stdout
    assert "not tuned: uncovered calibration" in stdout
    rows = json.loads(output.read_text())["hierarchical"]
    assert len(rows) == 5
    assert rows[0]["uncovered"] == "uncovered calibration"
    for row in rows[1:]:
        assert row["band"] == 128
        assert row["taps"] == 4
        assert row["speedup"] == 2.0


def test_no_optional_engines_means_no_substitute_timing(monkeypatch):
    import sys
    import numpy as np
    for module in ('pyfftw', 'mkl_fft', 'mkl_fft.interfaces'):
        monkeypatch.setitem(sys.modules, module, None)
    assert benchmark.available_engines() == []
    assert benchmark.reference_transforms(128, 1, np.zeros((1,128), np.complex64)) == []


def test_representative_targets_do_not_repeat_auto(monkeypatch):
    monkeypatch.setattr(benchmark.mf, 'targets', lambda: ['AVX3', 'AVX2', 'SSE4'])
    monkeypatch.setattr(benchmark.mf, 'backend', lambda: 'AVX3')
    assert benchmark.benchmark_targets() == ['auto', 'AVX2']
    monkeypatch.setattr(benchmark.mf, 'backend', lambda: 'AVX2')
    assert benchmark.benchmark_targets() == ['auto']
    monkeypatch.setattr(benchmark.mf, 'targets', lambda: ['NEON_BF16', 'NEON', 'NEON_WITHOUT_AES'])
    monkeypatch.setattr(benchmark.mf, 'backend', lambda: 'NEON_BF16')
    assert benchmark.benchmark_targets() == ['auto']
