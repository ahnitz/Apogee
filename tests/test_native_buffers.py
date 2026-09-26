"""The native boundary must reject malformed buffers before any writes."""
import numpy as np
import pytest
from matchedfilter import _core


@pytest.fixture(params=['flat','hier'])
def native(request):
    n=128
    f=_core.MF(n,1,1) if request.param=='flat' else _core.HMF(n,1,1,5.5,.01,64,1,8)
    if request.param=='hier': f.set_threshold(0.)
    data=np.ones(n,np.complex64)
    f.set_data(0,data); f.set_template(0,data)
    return f,data  # hierarchical native ingestion retains the caller's pointer


def buffers(size=128,blocks=1):
    return [np.full(size,-777,np.int64),np.full(size,-777,np.complex64),
            np.full(size,-777,np.float32),np.full(blocks,-777,np.int32)]


@pytest.mark.parametrize('entry',['run','series'])
@pytest.mark.parametrize('short',[0,1,2,3])
def test_small_outputs_leave_backing_allocation_untouched(native,entry,short):
    f,data=native
    backing=buffers()
    exposed=list(backing)
    exposed[short]=backing[short][:1] if short!=3 else backing[short][:0]
    with pytest.raises(ValueError,match='output'):
        if entry=='run': f.run(0,1,0,1,1,0.,0,128,*exposed)
        else: f.run_series(data,np.array([0],np.uintp),np.array([0],np.uintp),
                           np.array([128],np.uintp),0,1,1,0.,*exposed)
    for a in backing: assert (a==-777).all()


@pytest.mark.parametrize('case',['empty','mismatched','unaligned_bytes','different_bins','overflow','zero_bins','bad_template'])
def test_malformed_series_layout(native,case):
    f,data=native
    st=np.array([0,0],np.uintp); ws=np.array([0,0],np.uintp); we=np.array([128,128],np.uintp)
    bs=1; t0=0
    if case=='empty': st=ws=we=np.empty(0,np.uintp)
    elif case=='mismatched': we=we[:1]
    elif case=='unaligned_bytes': st=b'x'
    elif case=='different_bins': we[1]=127
    elif case=='overflow': st[1]=np.iinfo(np.uintp).max
    elif case=='zero_bins': bs=0
    elif case=='bad_template': t0=1
    out=buffers(256,2)
    with pytest.raises(ValueError): f.run_series(data,st,ws,we,t0,1,bs,0.,*out)
    for a in out: assert (a==-777).all()


def test_scratch_reuse_and_optional_magnitude(native):
    f,data=native
    for bs in (128,1,16,128):
        count=128//bs
        out=buffers(count)
        out[2]=np.empty(0,np.float32)
        f.run(0,1,0,1,bs,0.,0,128,*out)
        assert out[0][0]==0
        assert out[1][0]==pytest.approx(128+0j)
