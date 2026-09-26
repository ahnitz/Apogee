"""Public API parity at boundaries and across plan state transitions."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=['cpu','gpu'])
def device(request):
    if request.param=='cpu': return 'cpu'
    dev=usable_gpu()
    if dev is None: pytest.skip('no usable GPU')
    return dev


@pytest.fixture(params=['flat','hier'])
def plan(request,device):
    if request.param=='flat':
        return mf.MatchedFilter(1024,2,2,device=device)
    f=mf.HierarchicalFilter(1024,2,2,band=256,device=device)
    f.set_reference(np.ones(1024,np.float32))
    f.set_coarse_threshold(0.)
    return f


def populate(f):
    rng=np.random.default_rng(882)
    for setter in (f.set_templates,f.set_data):
        setter((rng.normal(size=(2,1024))+1j*rng.normal(size=(2,1024))).astype(np.complex64))


def test_equal_row_count_different_shape(plan):
    populate(plan)
    full=plan.run().copy()
    for d,t in (((0,1),(0,2)),((0,2),(0,1))):
        p,c=plan.run(data=d,templates=t,counts=True)
        assert p.shape==(d[1],t[1],1)
        np.testing.assert_array_equal(p['index'],full['index'][:d[1],:t[1]])
        np.testing.assert_allclose(p['value'],full['value'][:d[1],:t[1]],rtol=1e-5,atol=1e-4)
        assert c.shape==(d[1],t[1])


@pytest.mark.parametrize('index',[-1,2])
def test_index_bounds(plan,index):
    for setter in (plan.set_data,plan.set_templates):
        with pytest.raises(IndexError): setter(np.ones(1024,np.complex64),index=index)


@pytest.mark.parametrize('binsize',[0,-1])
def test_invalid_binsize(plan,binsize):
    populate(plan)
    with pytest.raises(ValueError): plan.nbins(binsize)
    with pytest.raises(ValueError): plan.run(binsize=binsize)


def test_failed_data_set_does_not_enable_run(plan):
    with pytest.raises(ValueError): plan.set_data(np.ones((2,3),np.complex64))
    with pytest.raises(ValueError,match='no data'): plan.run()


def test_refinement_stats_count_work_not_detections(device):
    f=mf.HierarchicalFilter(1024,2,2,band=256,device=device)
    f.set_reference(np.ones(1024,np.float32)); f.set_coarse_threshold(0.)
    populate(f)
    p=f.run(threshold=1e10,binsize=1)
    assert (p['index']==-1).all()
    assert f.stats==(4,4)
    assert f.refine_rate==1.
    f.set_coarse_threshold(1e10)
    f.run()
    assert f.stats==(8,4)
    assert f.refine_rate==.5


def test_threshold_reset_and_reference_change(device,monkeypatch):
    def lookup(power,n,snr,fd,band): return float(power[0])+snr
    monkeypatch.setattr(mf,'choose_threshold',lookup)
    f=mf.HierarchicalFilter(1024,1,1,band=256,snr=5.5,device=device)
    ref=np.ones(1024,np.float32); f.set_reference(ref)
    def threshold():
        return f._gpu_calibration(5.5)[2] if f._gpu is not None else f._ensure().coarse_threshold(5.5)
    assert threshold()==pytest.approx(6.5)
    f.set_coarse_threshold(0.)
    assert threshold()==0.
    f.set_coarse_threshold(None)
    assert threshold()==pytest.approx(6.5)
    ref[0]=2.; f.set_reference(ref)
    assert threshold()==pytest.approx(7.5)
    f.set_first_stage(6.)
    assert threshold()==pytest.approx(8.)
    f.set_first_stage(None)
    assert threshold()==pytest.approx(7.5)


@pytest.mark.parametrize('bad',['zero','negative','nan','shape'])
def test_invalid_reference(device,bad):
    f=mf.HierarchicalFilter(1024,band=256,device=device)
    p=np.ones(1024,np.float32)
    if bad=='zero': p[:]=0
    elif bad=='negative': p[0]=-1
    elif bad=='nan': p[0]=np.nan
    else: p=p.reshape(2,512)
    with pytest.raises(ValueError): f.set_reference(p)
    assert f._pending_ref is None


def test_partial_initialization_checks_requested_rows(plan):
    x=np.ones(1024,np.complex64)
    plan.set_templates(x,index=0); plan.set_data(x,index=0)
    assert plan.run(data=(0,1),templates=(0,1)).shape==(1,1,1)
    with pytest.raises(ValueError,match='no data'): plan.run(templates=(0,1))
    with pytest.raises(ValueError,match='no templates'): plan.run(data=(0,1))
    plan.set_templates(x,index=1); plan.set_data(x,index=1)
    assert plan.run().shape==(2,2,1)


def test_series_requires_fresh_data_before_run(plan):
    populate(plan)
    plan.run_series(np.ones(1024,np.complex64),[0],[0],[1024])
    with pytest.raises(ValueError,match='no data'): plan.run()
    plan.set_data(np.ones((2,1024),np.complex64))
    assert plan.run().shape==(2,2,1)


def test_raw_output_types(plan):
    populate(plan)
    (idx,val),counts=plan.run(raw=True,counts=True)
    assert idx.dtype==np.int64 and val.dtype==np.complex64
    assert counts.dtype==np.int32


@pytest.mark.parametrize('kwargs',[{'ndata':0},{'ntemplates':0},{'band':32},{'band':1024},{'band':123},{'taps':0},{'taps':3}])
def test_invalid_constructor(device,kwargs):
    with pytest.raises(ValueError): mf.HierarchicalFilter(1024,device=device,**kwargs)


@pytest.mark.parametrize('threshold',[-1,np.nan,np.inf])
def test_invalid_coarse_threshold(device,threshold):
    f=mf.HierarchicalFilter(1024,band=256,device=device)
    with pytest.raises(ValueError): f.set_coarse_threshold(threshold)
