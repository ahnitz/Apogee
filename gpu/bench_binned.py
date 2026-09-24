"""Baseline vs per-bin kernel, same harness, same shape."""
import ctypes, sys, time, pathlib, math
sys.path.insert(0,'/home/ahnitz/projects/claude/searchdev/work/peak-fft/python')
import numpy as np
from matchedfilter import _vkcompute as V

def build(ctx, n, nbind, blobdir, name):
    vk = ctx.vk
    blob = (pathlib.Path(blobdir)/name).read_bytes()
    code = (ctypes.c_ubyte*len(blob)).from_buffer_copy(blob)
    sm = V._ShaderModule(16, None, 0, len(blob), ctypes.cast(code, V._vp))
    mod = V._vp(); vk.vkCreateShaderModule(ctx.device, ctypes.byref(sm), None, ctypes.byref(mod))
    binds = (V._LayoutBinding*nbind)(*[V._LayoutBinding(i,V._DESC_STORAGE_BUFFER,1,V._STAGE_COMPUTE,None) for i in range(nbind)])
    sli = V._SetLayoutCreate(32,None,0,nbind,binds); sl=V._vp()
    vk.vkCreateDescriptorSetLayout(ctx.device,ctypes.byref(sli),None,ctypes.byref(sl))
    push = V._PushRange(V._STAGE_COMPUTE,0,8)
    ls=(V._vp*1)(sl)
    pli=V._PipelineLayoutCreate(30,None,0,1,ctypes.cast(ls,V._vp),1,ctypes.pointer(push))
    lay=V._vp(); vk.vkCreatePipelineLayout(ctx.device,ctypes.byref(pli),None,ctypes.byref(lay))
    st=V._StageCreate(18,None,0,V._STAGE_COMPUTE,mod,b"main",None)
    ci=V._ComputePipelineCreate(29,None,0,st,lay,None,0); pp=V._vp()
    vk.vkCreateComputePipelines(ctx.device,None,1,ctypes.byref(ci),None,ctypes.byref(pp))
    return pp, lay, sl

def run(n, nd, nt, nbind, blobdir, name, push, reps=200, check=False):
    ctx = V.Context(0); vk = ctx.vk
    rng = np.random.default_rng(1)
    d = (rng.standard_normal((nd,n))+1j*rng.standard_normal((nd,n))).astype(np.complex64)
    h = (rng.standard_normal((nt,n))+1j*rng.standard_normal((nt,n))).astype(np.complex64)
    h /= np.linalg.norm(h,axis=1,keepdims=True)
    pp, lay, sl = build(ctx, n, nbind, blobdir, name)
    nbins = n >> push[1] if nbind==5 else 1
    bufs=[V._Buffer(ctx,d.size*8), V._Buffer(ctx,h.size*8), V._Buffer(ctx,nd*nt*nbins*4)]
    if nbind==5: bufs += [V._Buffer(ctx,nd*nt*nbins*4), V._Buffer(ctx,nd*nt*nbins*8)]
    bufs[0].write(d); bufs[1].write(h)
    sizes=(V._PoolSize*1)(V._PoolSize(V._DESC_STORAGE_BUFFER,nbind))
    dp=V._DescPoolCreate(33,None,0,1,1,sizes); pool=V._vp()
    vk.vkCreateDescriptorPool(ctx.device,ctypes.byref(dp),None,ctypes.byref(pool))
    sls=(V._vp*1)(sl); da=V._DescSetAlloc(34,None,pool,1,ctypes.cast(sls,V._vp)); ds=V._vp()
    vk.vkAllocateDescriptorSets(ctx.device,ctypes.byref(da),ctypes.byref(ds))
    infos=(V._DescBufferInfo*nbind)(*[V._DescBufferInfo(b.handle,0,V._WHOLE_SIZE) for b in bufs])
    w=(V._WriteDescSet*nbind)(*[V._WriteDescSet(35,None,ds,i,0,1,V._DESC_STORAGE_BUFFER,None,ctypes.pointer(infos[i]),None) for i in range(nbind)])
    vk.vkUpdateDescriptorSets(ctx.device,nbind,w,0,None)
    def rec(k):
        cb=V._CmdBufAlloc(40,None,ctx.command_pool,0,1); cmd=V._vp()
        vk.vkAllocateCommandBuffers(ctx.device,ctypes.byref(cb),ctypes.byref(cmd))
        vk.vkBeginCommandBuffer(cmd,ctypes.byref(V._CmdBufBegin(42,None,0,None)))
        vk.vkCmdBindPipeline(cmd,V._BIND_POINT_COMPUTE,pp)
        sets=(V._vp*1)(ds)
        vk.vkCmdBindDescriptorSets(cmd,V._BIND_POINT_COMPUTE,lay,0,1,sets,0,None)
        pc=(ctypes.c_uint32*2)(*push)
        vk.vkCmdPushConstants(cmd,lay,V._STAGE_COMPUTE,0,8,ctypes.byref(pc))
        for _ in range(k): vk.vkCmdDispatch(cmd,nd*nt,1,1)
        vk.vkEndCommandBuffer(cmd); return cmd
    def go(cmd):
        cs=(V._vp*1)(cmd); s=V._SubmitInfo(4,None,0,None,None,1,cs,0,None)
        vk.vkQueueSubmit(ctx.queue,1,ctypes.byref(s),None); vk.vkQueueWaitIdle(ctx.queue)
    c1,ck=rec(1),rec(reps)
    for _ in range(3): go(ck)
    t0=time.perf_counter(); go(ck); t1=time.perf_counter()
    t2=time.perf_counter(); go(c1); t3=time.perf_counter()
    per=((t1-t0)-(t3-t2))/(reps-1)
    res=None
    if check:
        go(c1)
        mag=bufs[2].read(np.float32,nd*nt*nbins).reshape(nd,nt,nbins)
        idx=bufs[3].read(np.uint32,nd*nt*nbins).reshape(nd,nt,nbins) if nbind==5 else None
        val=bufs[4].read(np.float32,nd*nt*nbins*2).view(np.complex64).reshape(nd,nt,nbins) if nbind==5 else None
        res=(mag,idx,val,d,h)
    ctx.destroy(); return per,res

if __name__=="__main__":
    n,nd,nt=4096,64,512
    base,_ = run(n,nd,nt,3,'/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/spirv','tierb_%d.spv'%n,(nt,0))
    lg = int(math.log2(n))
    new,res = run(n,nd,nt,5,'/tmp/bench','new_%d.spv'%n,(nt,lg),check=True)
    print("baseline (mag only)   %.4f ms  %.1f Gpair-pt/s" % (base*1e3, nd*nt*n/base/1e9))
    print("per-bin (+idx,+value) %.4f ms  %.1f Gpair-pt/s   delta %+.1f%%"
          % (new*1e3, nd*nt*n/new/1e9, 100*(base-new)/base))
    mag,idx,val,d,h = res
    ok=True
    for (i,j) in [(0,0),(17,255),(63,511)]:
        ref = np.fft.ifft(d[i].astype(np.complex128)*np.conj(h[j]).astype(np.complex128))*n
        k = int(np.argmax(np.abs(ref)))
        if abs(mag[i,j,0]-abs(ref[k]))/abs(ref[k]) > 1e-5 or int(idx[i,j,0]) != k: ok=False
        print("   pair(%2d,%3d) gpu idx=%5d ref idx=%5d  mag %.4f/%.4f  val %.4f%+.4fj / %.4f%+.4fj"
              % (i,j,idx[i,j,0],k,mag[i,j,0],abs(ref[k]),val[i,j,0].real,val[i,j,0].imag,ref[k].real,ref[k].imag))
    print("   argmax+value correct:", ok)
