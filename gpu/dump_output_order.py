import sys, pathlib, ctypes
sys.path.insert(0,'/home/ahnitz/projects/claude/searchdev/work/peak-fft/python')
import numpy as np
from matchedfilter import _vkcompute as V
V._SPIRV = pathlib.Path('/tmp/bench')

def perm_for(n):
    ctx = V.Context(0); vk = ctx.vk
    rng = np.random.default_rng(7)
    d = (rng.standard_normal((1,n))+1j*rng.standard_normal((1,n))).astype(np.complex64)
    h = (rng.standard_normal((1,n))+1j*rng.standard_normal((1,n))).astype(np.complex64)
    pipe, layout, sl = ctx.pipeline(n)
    bd, bh = V._Buffer(ctx, d.size*8), V._Buffer(ctx, h.size*8)
    bm = V._Buffer(ctx, n*2*4); bd.write(d); bh.write(h)
    sizes=(V._PoolSize*1)(V._PoolSize(V._DESC_STORAGE_BUFFER,3))
    dp=V._DescPoolCreate(33,None,0,1,1,sizes); pool=V._vp()
    vk.vkCreateDescriptorPool(ctx.device,ctypes.byref(dp),None,ctypes.byref(pool))
    sls=(V._vp*1)(sl); da=V._DescSetAlloc(34,None,pool,1,ctypes.cast(sls,V._vp)); ds=V._vp()
    vk.vkAllocateDescriptorSets(ctx.device,ctypes.byref(da),ctypes.byref(ds))
    infos=(V._DescBufferInfo*3)(*[V._DescBufferInfo(b.handle,0,V._WHOLE_SIZE) for b in (bd,bh,bm)])
    w=(V._WriteDescSet*3)(*[V._WriteDescSet(35,None,ds,i,0,1,V._DESC_STORAGE_BUFFER,None,ctypes.pointer(infos[i]),None) for i in range(3)])
    vk.vkUpdateDescriptorSets(ctx.device,3,w,0,None)
    cb=V._CmdBufAlloc(40,None,ctx.command_pool,0,1); cmd=V._vp()
    vk.vkAllocateCommandBuffers(ctx.device,ctypes.byref(cb),ctypes.byref(cmd))
    vk.vkBeginCommandBuffer(cmd,ctypes.byref(V._CmdBufBegin(42,None,1,None)))
    vk.vkCmdBindPipeline(cmd,V._BIND_POINT_COMPUTE,pipe)
    sets=(V._vp*1)(ds)
    vk.vkCmdBindDescriptorSets(cmd,V._BIND_POINT_COMPUTE,layout,0,1,sets,0,None)
    one=V._u32(1); vk.vkCmdPushConstants(cmd,layout,V._STAGE_COMPUTE,0,4,ctypes.byref(one))
    vk.vkCmdDispatch(cmd,1,1,1); vk.vkEndCommandBuffer(cmd)
    cmds=(V._vp*1)(cmd); s=V._SubmitInfo(4,None,0,None,None,1,cmds,0,None)
    vk.vkQueueSubmit(ctx.queue,1,ctypes.byref(s),None); vk.vkQueueWaitIdle(ctx.queue)
    got = bm.read(np.float32, n*2).view(np.complex64)
    want = np.fft.ifft(d[0]*np.conj(h[0]))*n
    perm = np.array([int(np.argmin(np.abs(want-got[k]))) for k in range(n)])
    err = np.abs(want[perm]-got).max()/np.abs(want).max()
    ctx.destroy()
    return perm, err

for n in (1024, 2048, 4096, 8192, 16384):
    p, e = perm_for(n)
    np.save('/tmp/bench/perm_%d.npy'%n, p)
    print('n=%-6d saved, unique=%d, max rel err %.1e' % (n, len(set(p.tolist())), e))
