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
