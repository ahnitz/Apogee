#!/usr/bin/env python3
"""Compare production coarse packing with a supplied candidate SPIR-V.

100 ordered dispatches per submission; 11 alternating rounds, output checked
bit-for-bit in both packing modes. Times include barriers and submission.
"""
import argparse
from pathlib import Path
import ctypes as C, numpy as np, time, json
from matchedfilter import _vkcompute as V
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate-spv', type=Path, required=True)
args=parser.parse_args()
candidate=str(args.candidate_spv.resolve())
c=V.Context(0); rng=np.random.default_rng(6); results=[]
try:
 for n,band,rows,packed in [(4096,128,64,1),(16384,512,256,1),(16384,4096,256,1),(4096,256,64,0)]:
  d=(rng.normal(size=(rows,n))+1j*rng.normal(size=(rows,n))).astype(np.complex64)
  src=V._Buffer(c,d.nbytes);src.write(d)
  dst=V._Buffer(c,rows*band*(4 if packed else 8),readback=True)
  cmds=[]
  for filename in ['pack_coarse.spv',candidate]:
   pipe,layout,sl=c._build_pipeline(filename,filename,2,16)
   ds=c._descriptor_set(sl,[src,dst]);cmd=V._vp()
   V._check(c.vk.vkAllocateCommandBuffers(c.device,C.byref(V._CmdBufAlloc(40,None,c.command_pool,0,1)),C.byref(cmd)),'alloc')
   c.vk.vkBeginCommandBuffer(cmd,C.byref(V._CmdBufBegin(42,None,0,None)))
   c.vk.vkCmdBindPipeline(cmd,V._BIND_POINT_COMPUTE,pipe)
   c.vk.vkCmdBindDescriptorSets(cmd,V._BIND_POINT_COMPUTE,layout,0,1,(V._vp*1)(ds),0,None)
   pc=(C.c_uint32*4)(n,band,rows*band,packed)
   c.vk.vkCmdPushConstants(cmd,layout,V._STAGE_COMPUTE,0,16,C.byref(pc))
   for i in range(100):
    c.vk.vkCmdDispatch(cmd,(rows*band+255)//256,1,1)
    mb=V._MemBarrier(46,None,V._ACCESS_SHADER_WRITE,V._ACCESS_SHADER_READ|V._ACCESS_SHADER_WRITE|0x2000)
    c.vk.vkCmdPipelineBarrier(cmd,V._STAGE_COMPUTE_BIT,V._STAGE_COMPUTE_BIT|0x4000,0,1,C.byref(mb),0,None,0,None)
   c.vk.vkEndCommandBuffer(cmd);cmds.append(cmd)
   c._submit(cmd)
   got=dst.read(np.uint32,rows*band*(1 if packed else 2))
   want=V._pack_half2(d[:,:band]).ravel() if packed else np.ascontiguousarray(d[:,:band]).view(np.uint32).ravel()
   np.testing.assert_array_equal(got,want)
  times=[[],[]]
  for rep in range(11):
   for j in ([0,1] if rep%2==0 else [1,0]):
    t=time.perf_counter();c._submit(cmds[j]);times[j].append((time.perf_counter()-t)*1e6/100)
  a,b=map(np.median,times)
  result=dict(n=n,band=band,rows=rows,packed=packed,old_us=a,new_us=b,ratio=b/a,old_range=[min(times[0]),max(times[0])],new_range=[min(times[1]),max(times[1])])
  print(json.dumps(result),flush=True);results.append(result)
  src.destroy();dst.destroy()
finally:c.destroy()
