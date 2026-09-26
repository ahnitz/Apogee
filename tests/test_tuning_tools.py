"""Regression coverage for cost regeneration and current table formats."""
import importlib.util
from pathlib import Path
import numpy as np
import pytest


def load_tuner():
    path=Path(__file__).resolve().parents[1]/'tools'/'hmf_tune.py'
    spec=importlib.util.spec_from_file_location('tuner_under_test',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('row', [
    'ACC2 4096 8 6.00 0.99 16.0 1.000 0.001',
    'ACC2R 4096 8 6.00 0.99 16.0 1.000 0.001',
    'ACC 4096 256 2 8 6.00 0.99 16.0 1.000 0.001',
])
def test_retune_cost_current_and_legacy_accuracy(tmp_path,monkeypatch,row):
    monkeypatch.chdir(tmp_path)
    tuner=load_tuner()
    accuracy=tmp_path/'accuracy.txt'; accuracy.write_text(row+'\n')
    out=tmp_path/'cost.txt'
    calls=[]
    def sweep(n,power,snr,configs):
        assert n==4096 and snr==6.
        calls.append(configs)
        return {c:1. for c in configs},0.
    monkeypatch.setattr(tuner,'cost_sweep_one_reference',sweep)
    tuner.retune_cost(accuracy,out,verbose=False)
    rows=[line.split() for line in out.read_text().splitlines() if line.startswith('COST ')]
    assert calls and rows
    assert {64,128,256,512,1024,2048}=={int(r[2]) for r in rows}
    assert all(len(r)==10 and float(r[-1])==1. for r in rows)
    assert all(float(r[5])==6. for r in rows)


def test_retune_rejects_empty_accuracy_without_overwriting(tmp_path):
    tuner=load_tuner()
    accuracy=tmp_path/'empty.txt'; accuracy.write_text('# no rows\n')
    out=tmp_path/'cost.txt'; out.write_text('existing')
    with pytest.raises(ValueError,match='no supported accuracy'):
        tuner.retune_cost(accuracy,out,verbose=False)
    assert out.read_text()=='existing'


def test_hier_bench_cli_uses_current_raw_results(tmp_path):
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'tools/hier_bench.py'),
        '--n','1024','--templates','4','--series','8192','--taps','128',
        '--inject','2','--reps','1','--band','256','--no-profile'],
        cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'proof:' in result.stdout


def test_retune_cli_defines_helpers_before_entrypoint(tmp_path):
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    accuracy=tmp_path/'accuracy.txt'
    accuracy.write_text('ACC2 128 8 6.0 .99 8.0 1.0 .001\n')
    output=tmp_path/'cost.txt'
    result=subprocess.run([sys.executable,str(root/'tools/hmf_tune.py'),
        '--retune-cost',str(accuracy),'--out',str(output)],
        cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'COST 128 64' in output.read_text()


def test_cost_tuner_import_does_not_require_scipy(tmp_path, monkeypatch):
    import sys
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, 'scipy', None)
    monkeypatch.setitem(sys.modules, 'hmf_design', None)
    tuner=load_tuner()
    reference=tuner.make_ref(1024,256,.99,16.)
    assert reference.shape==(1024,)
    assert np.isfinite(reference).all()
