"""Dispatching the embedded SPIR-V through Vulkan, with ctypes.

No slangpy, no Vulkan SDK, no compiled host code: the loader is whatever the
user's system provides, and everything above it is the twenty-odd entry points
a compute-only workload needs.  That keeps the wheel self-contained -- it
carries kernels, not a toolchain -- and keeps the GPU path out of the way of
callers who only ever use the CPU.

Scope is deliberately compute-only.  No swapchain, no images, no graphics
pipeline, one queue, one descriptor set.
"""
import ctypes
import pathlib

import numpy as np

from . import _vulkan
from ._shared import empty_shared, shared_buffer, shared_key, write_input

_SPIRV = pathlib.Path(__file__).resolve().parent / "spirv"

_MANIFEST = None


def _manifest():
    global _MANIFEST
    if _MANIFEST is None:
        try:
            import json
            _MANIFEST = json.loads((_SPIRV / "manifest.json").read_text())
        except Exception:
            _MANIFEST = {}
    return _MANIFEST

#: The per-bin table aliases the 8 KB exchange staging: CAP=1024 complex =
#: 2048 uints. Past that the kernel needs its own array and the LDS cost
#: halves occupancy, so this refuses rather than silently getting slower.
_MAX_BINS = 2048

#: Must match COARSE_TILE_T in tools/build_spirv.py -- the kernel is
#: compiled with the tile baked in, so the dispatch has to agree.
_COARSE_TILE_T = {128: 2, 256: 2, 512: 4, 1024: 2}


def _use_c16(band):
    """Half-width coarse path, only where filling a wave pays for it.

    WG = band/16, so a band under 512 gives a workgroup SMALLER than one
    wave32 and packing PPG = 512/band pairs into it fills the idle lanes.
    Measured at band 128 (WG 8, PPG 4): 1.911 -> 0.865 ms, 2.2x.

    At band 512 the workgroup is already a full wave and there is nothing
    to fill, so the half2 conversions in the stage are pure added cost --
    2.239 -> 2.615 ms, 17% SLOWER, and band 1024 11% slower. Those are
    means of three runs; single runs on this part vary by ~15% at band 128
    and ~7% at 512, which is wide enough that one measurement either way
    would have supported the wrong answer.
    """
    return True   # one-bin specialised coarse kernel; applies at every band


def _pack_half2(a):
    """complex64 -> one uint32 per value, real in the low half.

    The coarse stage is bandwidth bound -- 978 GB/s at 3.19 FLOP/byte -- so
    its two big inputs ship at half width. Packed into uint32 rather than a
    half2 buffer so no 16-bit storage extension is needed.

    Done ONCE on upload: every row is reused across the whole N x M pair
    grid, so the conversion amortises to nothing.

    Coarse only. The refine stage reads the full-precision data/tmpl
    buffers, which is why survivors still get an exact peak.
    """
    a = np.ascontiguousarray(a, np.complex64)
    if np.little_endian:
        # Complex storage is already [real, imag]. Convert the interleaved
        # components in one pass rather than allocating widened integers,
        # shifting, and ORing two separately converted arrays.
        return a.view(np.float32).astype(np.float16).view(np.uint32)
    re = a.real.astype(np.float16).view(np.uint16).astype(np.uint32)
    im = a.imag.astype(np.float16).view(np.uint16).astype(np.uint32)
    return np.ascontiguousarray(re | (im << 16), np.uint32)

#: Byte offsets into VkPhysicalDeviceProperties. The 5 leading uint32s, the
#: 256-byte name and the 16-byte UUID come to 292, padded to 296 because
#: VkPhysicalDeviceLimits contains 64-bit members; maxComputeSharedMemorySize
#: sits 216 bytes into those limits.
_OFF_SHARED_MEMORY = 296 + 216
_OFF_MAX_INVOCATIONS = 296 + 232

#: Bands that USE the tiled coarse kernel. It is built and validated for
#: 512 and 1024 as well, and deliberately not selected there.
#:
#: Tiling pays at 256 and only at 256, because the untiled workgroup is
#: BAND/16 threads and 16 is HALF A WAVE -- the other half idles. At 512
#: that is a full wave and at 1024 two, so there is no waste to recover,
#: while the tile's shared memory grows to 16 and 32 KB against 4 and costs
#: occupancy. Measured, hierarchical call, untiled against tiled:
#:
#:     n=8192  band 512   0.761 -> 0.730 ms   1.04x
#:     n=8192  band 512   0.417 -> 0.539 ms   0.77x
#:     n=16384 band 1024  0.973 -> 1.008 ms   0.97x
#:     n=16384 band 512   2.007 -> 1.664 ms   1.21x
#:
#: Noise around one. The 1.8x the tile buys at 256 does not generalise, and
#: assuming it did is what prompted the measurement.
#:
#: The tile must match the TILE the kernel was compiled with, or the
#: dispatch covers the wrong number of pairs.
#: EMPTY. This selected a separate fp32 tiled coarse kernel (coarse_N.spv)
#: that predates the fp16 work, and band 256 was still routed to it -- so
#: the band the teaser autotunes to ran with ZERO fp16 instructions while
#: every other band had been converted. Disassembly found it: 4125
#: instructions, 1351 fp32, no v_pk_* at all.
#:
#: On the converted kernel band 256 goes 1.109 -> 0.868 ms. Kept as an
#: empty dict rather than deleted so the selection point stays visible.
_COARSE_TILE = {}

# --- enough of the Vulkan enums to dispatch -------------------------------
_QUEUE_COMPUTE = 0x2
_BUF_STORAGE = 0x20
_BUF_INDIRECT = 0x100   # an indirect dispatch reads its group count from a buffer
_MEM_DEVICE_LOCAL, _MEM_HOST_VISIBLE, _MEM_HOST_COHERENT = 0x1, 0x2, 0x4
#: HOST_CACHED. The CPU reads the two output buffers and nothing else,
#: and reading uncached device-visible memory runs at about 240 MB/s --
#: measured, and enough to cost more than the kernel.
_MEM_HOST_CACHED = 0x8
_DESC_STORAGE_BUFFER = 7
_STAGE_COMPUTE = 0x20
_BIND_POINT_COMPUTE = 1
_ONE_TIME_SUBMIT = 0x1
_STAGE_COMPUTE_BIT = 0x800
_ACCESS_SHADER_READ, _ACCESS_SHADER_WRITE = 0x20, 0x40
_WHOLE_SIZE = 0xFFFFFFFFFFFFFFFF

_u32, _u64, _vp = ctypes.c_uint32, ctypes.c_uint64, ctypes.c_void_p

#: data, tmpl, peakIdx, peakVal -- confirmed against spirv/manifest.json,
#: generated by reflecting the compiled module, not by reading the source.
_NBIND = 4

#: ntmpl, winStart, winEnd, binsize, binShift, nbins, thrBits
_PUSH_BYTES = 28


def _struct(name, *fields):
    return type(name, (ctypes.Structure,), {"_fields_": list(fields)})


_QueueCreate = _struct("VkDeviceQueueCreateInfo",
                       ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                       ("queueFamilyIndex", _u32), ("queueCount", _u32),
                       ("pQueuePriorities", ctypes.POINTER(ctypes.c_float)))
_DeviceCreate = _struct("VkDeviceCreateInfo",
                        ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                        ("queueCreateInfoCount", _u32),
                        ("pQueueCreateInfos", ctypes.POINTER(_QueueCreate)),
                        ("enabledLayerCount", _u32), ("ppEnabledLayerNames", _vp),
                        ("enabledExtensionCount", _u32), ("ppEnabledExtensionNames", _vp),
                        ("pEnabledFeatures", _vp))
_BufferCreate = _struct("VkBufferCreateInfo",
                        ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                        ("size", _u64), ("usage", _u32), ("sharingMode", _u32),
                        ("queueFamilyIndexCount", _u32), ("pQueueFamilyIndices", _vp))
_MemAlloc = _struct("VkMemoryAllocateInfo",
                    ("sType", _u32), ("pNext", _vp),
                    ("allocationSize", _u64), ("memoryTypeIndex", _u32))
_MemReq = _struct("VkMemoryRequirements",
                  ("size", _u64), ("alignment", _u64), ("memoryTypeBits", _u32))
_MemType = _struct("VkMemoryType", ("propertyFlags", _u32), ("heapIndex", _u32))
_MemHeap = _struct("VkMemoryHeap", ("size", _u64), ("flags", _u32))
_MemProps = _struct("VkPhysicalDeviceMemoryProperties",
                    ("memoryTypeCount", _u32), ("memoryTypes", _MemType * 32),
                    ("memoryHeapCount", _u32), ("memoryHeaps", _MemHeap * 16))
_QueueFamily = _struct("VkQueueFamilyProperties",
                       ("queueFlags", _u32), ("queueCount", _u32),
                       ("timestampValidBits", _u32),
                       ("minImageTransferGranularity", _u32 * 3))
_ShaderModule = _struct("VkShaderModuleCreateInfo",
                        ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                        ("codeSize", ctypes.c_size_t), ("pCode", _vp))
_LayoutBinding = _struct("VkDescriptorSetLayoutBinding",
                         ("binding", _u32), ("descriptorType", _u32),
                         ("descriptorCount", _u32), ("stageFlags", _u32),
                         ("pImmutableSamplers", _vp))
_SetLayoutCreate = _struct("VkDescriptorSetLayoutCreateInfo",
                           ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                           ("bindingCount", _u32),
                           ("pBindings", ctypes.POINTER(_LayoutBinding)))
_PushRange = _struct("VkPushConstantRange",
                     ("stageFlags", _u32), ("offset", _u32), ("size", _u32))
_PipelineLayoutCreate = _struct("VkPipelineLayoutCreateInfo",
                                ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                                ("setLayoutCount", _u32), ("pSetLayouts", _vp),
                                ("pushConstantRangeCount", _u32),
                                ("pPushConstantRanges", ctypes.POINTER(_PushRange)))
_StageCreate = _struct("VkPipelineShaderStageCreateInfo",
                       ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                       ("stage", _u32), ("module", _vp),
                       ("pName", ctypes.c_char_p), ("pSpecializationInfo", _vp))
_ComputePipelineCreate = _struct("VkComputePipelineCreateInfo",
                                 ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                                 ("stage", _StageCreate), ("layout", _vp),
                                 ("basePipelineHandle", _vp),
                                 ("basePipelineIndex", ctypes.c_int32))
_PoolSize = _struct("VkDescriptorPoolSize", ("type", _u32), ("descriptorCount", _u32))
_DescPoolCreate = _struct("VkDescriptorPoolCreateInfo",
                          ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                          ("maxSets", _u32), ("poolSizeCount", _u32),
                          ("pPoolSizes", ctypes.POINTER(_PoolSize)))
_DescSetAlloc = _struct("VkDescriptorSetAllocateInfo",
                        ("sType", _u32), ("pNext", _vp), ("descriptorPool", _vp),
                        ("descriptorSetCount", _u32), ("pSetLayouts", _vp))
_DescBufferInfo = _struct("VkDescriptorBufferInfo",
                          ("buffer", _vp), ("offset", _u64), ("range", _u64))
_WriteDescSet = _struct("VkWriteDescriptorSet",
                        ("sType", _u32), ("pNext", _vp), ("dstSet", _vp),
                        ("dstBinding", _u32), ("dstArrayElement", _u32),
                        ("descriptorCount", _u32), ("descriptorType", _u32),
                        ("pImageInfo", _vp),
                        ("pBufferInfo", ctypes.POINTER(_DescBufferInfo)),
                        ("pTexelBufferView", _vp))
_CmdPoolCreate = _struct("VkCommandPoolCreateInfo",
                         ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                         ("queueFamilyIndex", _u32))
_CmdBufAlloc = _struct("VkCommandBufferAllocateInfo",
                       ("sType", _u32), ("pNext", _vp), ("commandPool", _vp),
                       ("level", _u32), ("commandBufferCount", _u32))
_CmdBufBegin = _struct("VkCommandBufferBeginInfo",
                       ("sType", _u32), ("pNext", _vp), ("flags", _u32),
                       ("pInheritanceInfo", _vp))
_SubmitInfo = _struct("VkSubmitInfo",
                      ("sType", _u32), ("pNext", _vp),
                      ("waitSemaphoreCount", _u32), ("pWaitSemaphores", _vp),
                      ("pWaitDstStageMask", _vp),
                      ("commandBufferCount", _u32),
                      ("pCommandBuffers", ctypes.POINTER(_vp)),
                      ("signalSemaphoreCount", _u32), ("pSignalSemaphores", _vp))


_MemBarrier = _struct("VkMemoryBarrier",
                      ("sType", _u32), ("pNext", _vp),
                      ("srcAccessMask", _u32), ("dstAccessMask", _u32))


from ._errors import UnsupportedSize      # noqa: F401  (re-export)
from ._gpu_cache import InputUploads


class VulkanError(RuntimeError):
    pass


def _check(rc, what):
    if rc != 0:
        raise VulkanError("%s failed with VkResult %d" % (what, rc))


class _Buffer:
    """A storage buffer plus its memory, mapped for the lifetime of the object.

    Host-visible throughout, with DEVICE_LOCAL preferred when the driver
    offers it.  On an integrated GPU that combination is the whole of memory,
    so this is not a compromise; on a discrete card it is, and a staging copy
    will be needed there -- deliberately not written until there is a discrete
    card to measure it on, because an unmeasured transfer path is exactly the
    kind of code that looks right and halves throughput.
    """

    def __init__(self, ctx, nbytes, readback=False, usage=_BUF_STORAGE):
        self.ctx, self.nbytes = ctx, max(int(nbytes), 4)
        vk = ctx.vk
        info = _BufferCreate(12, None, 0, self.nbytes, usage, 0, 0, None)
        self.handle = _vp()
        _check(vk.vkCreateBuffer(ctx.device, ctypes.byref(info), None,
                                 ctypes.byref(self.handle)), "vkCreateBuffer")
        req = _MemReq()
        vk.vkGetBufferMemoryRequirements(ctx.device, self.handle, ctypes.byref(req))
        alloc = _MemAlloc(5, None, req.size, ctx.memory_type(req.memoryTypeBits, readback))
        self.memory = _vp()
        _check(vk.vkAllocateMemory(ctx.device, ctypes.byref(alloc), None,
                                   ctypes.byref(self.memory)), "vkAllocateMemory")
        _check(vk.vkBindBufferMemory(ctx.device, self.handle, self.memory, 0),
               "vkBindBufferMemory")
        self.ptr = _vp()
        _check(vk.vkMapMemory(ctx.device, self.memory, 0, _WHOLE_SIZE, 0,
                              ctypes.byref(self.ptr)), "vkMapMemory")

    def write(self, array):
        flat = np.ascontiguousarray(array)
        ctypes.memmove(self.ptr, flat.ctypes.data, flat.nbytes)

    def read(self, dtype, count):
        out = np.empty(count, dtype=dtype)
        ctypes.memmove(out.ctypes.data, self.ptr, out.nbytes)
        return out

    def destroy(self):
        vk, dev = self.ctx.vk, self.ctx.device
        if self.handle:
            vk.vkUnmapMemory(dev, self.memory)
            vk.vkDestroyBuffer(dev, self.handle, None)
            vk.vkFreeMemory(dev, self.memory, None)
            self.handle = None


class Context(InputUploads):
    """One Vulkan device, its compute queue, and the pipelines built on it."""

    def __init__(self, index=0):
        vk, err = _vulkan._load()
        if vk is None:
            raise VulkanError(err)
        self.vk = vk
        # VkDeviceSize is 64-bit. Without argtypes ctypes passes a Python int
        # as a C int and the offset and size arrive truncated, which for a
        # fill is silent corruption rather than an error.
        vk.vkCmdFillBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_uint64, ctypes.c_uint64,
                                       ctypes.c_uint32]
        vk.vkCmdDispatchIndirect.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_uint64]
        self._pipelines = {}
        self._batches = {}
        self._storage = {}
        self._storage_users = {}
        self._record_storage = {}
        self._record_pools = {}
        self._hier = {}
        self._uploaded = {"data": {}, "tmpl": {}}

        app = _vulkan._AppInfo(0, None, b"matchedfilter", 1, b"matchedfilter", 1,
                               (1 << 22) | (1 << 12))
        ci = _vulkan._InstInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
        self.instance = _vp()
        _check(vk.vkCreateInstance(ctypes.byref(ci), None,
                                   ctypes.byref(self.instance)), "vkCreateInstance")

        count = _u32(0)
        vk.vkEnumeratePhysicalDevices(self.instance, ctypes.byref(count), None)
        if index >= count.value:
            raise VulkanError("no Vulkan device with index %d" % index)
        handles = (_vp * count.value)()
        vk.vkEnumeratePhysicalDevices(self.instance, ctypes.byref(count), handles)
        self.physical = _vp(handles[index])

        self.queue_family = self._compute_queue_family()
        priority = (ctypes.c_float * 1)(1.0)
        qci = _QueueCreate(2, None, 0, self.queue_family, 1, priority)
        dci = _DeviceCreate(3, None, 0, 1, ctypes.pointer(qci),
                            0, None, 0, None, None)
        self.device = _vp()
        _check(vk.vkCreateDevice(self.physical, ctypes.byref(dci), None,
                                 ctypes.byref(self.device)), "vkCreateDevice")
        self.queue = _vp()
        vk.vkGetDeviceQueue(self.device, self.queue_family, 0,
                            ctypes.byref(self.queue))

        # What this device will actually give a workgroup. Several kernels
        # are built at 64 KB because that is fastest here, and Apple allows
        # 32 KB -- so the size has to be asked for rather than assumed. A
        # software rasteriser will not reveal the mistake: llvmpipe reports
        # 32 KB and runs a 64 KB kernel regardless.
        props = (ctypes.c_ubyte * 2048)()
        vk.vkGetPhysicalDeviceProperties(self.physical, ctypes.byref(props))
        self.max_shared_memory = int(ctypes.cast(
            ctypes.byref(props, _OFF_SHARED_MEMORY),
            ctypes.POINTER(_u32))[0])
        # n=16384 needs a 1024-thread workgroup, which is exactly the limit
        # on Apple hardware and on this one. A device offering fewer cannot
        # run the larger kernels at all, and should say so rather than fail
        # to create a pipeline.
        self.max_invocations = int(ctypes.cast(
            ctypes.byref(props, _OFF_MAX_INVOCATIONS),
            ctypes.POINTER(_u32))[0])

        self.max_dispatch_x = int(ctypes.cast(
            ctypes.byref(props, _OFF_MAX_INVOCATIONS - 12),
            ctypes.POINTER(_u32))[0])

        self.mem_props = _MemProps()
        vk.vkGetPhysicalDeviceMemoryProperties(self.physical,
                                               ctypes.byref(self.mem_props))

        pool_info = _CmdPoolCreate(39, None, 0, self.queue_family)
        self.command_pool = _vp()
        _check(vk.vkCreateCommandPool(self.device, ctypes.byref(pool_info), None,
                                      ctypes.byref(self.command_pool)),
               "vkCreateCommandPool")

    def _compute_queue_family(self):
        """The first family with COMPUTE.

        Not necessarily a dedicated compute family: a dedicated one can be
        faster on discrete hardware, but choosing it is a tuning decision that
        needs measuring on the device in question, and the universal family
        is always correct.
        """
        count = _u32(0)
        self.vk.vkGetPhysicalDeviceQueueFamilyProperties(
            self.physical, ctypes.byref(count), None)
        families = (_QueueFamily * count.value)()
        self.vk.vkGetPhysicalDeviceQueueFamilyProperties(
            self.physical, ctypes.byref(count), families)
        for i, fam in enumerate(families):
            if fam.queueFlags & _QUEUE_COMPUTE:
                return i
        raise VulkanError("device exposes no compute queue")

    def memory_type(self, allowed_bits, readback=False):
        """A memory type for this buffer; host-visible either way.

        Direction decides the preference, because the two wants are opposed.
        A buffer the CPU WRITES wants DEVICE_LOCAL and host-visible -- the
        resizable-BAR heap -- which is write-combined: streaming stores go
        straight to the card. A buffer the CPU READS wants HOST_CACHED,
        because reads from write-combined memory are uncached and crawl.

        Measured on gfx1151: the peak outputs came back at 240 MB/s, so at
        n=16384 with ten bins the 3.9 MB readback cost 16 ms against 24 ms
        for the kernel that produced it. Same allocation, one flag.
        """
        want = _MEM_HOST_VISIBLE | _MEM_HOST_COHERENT
        order = ((want | _MEM_HOST_CACHED, want | _MEM_DEVICE_LOCAL, want)
                 if readback else (want | _MEM_DEVICE_LOCAL, want))
        for require in order:
            for i in range(self.mem_props.memoryTypeCount):
                flags = self.mem_props.memoryTypes[i].propertyFlags
                if allowed_bits & (1 << i) and (flags & require) == require:
                    return i
        raise VulkanError("no host-visible memory type available")

    # ---- pipeline ---------------------------------------------------------
    def _refine_file(self, n):
        """refineListed for `n`, portable build where the device needs it."""
        info = (_manifest().get("modules", {}).get(str(n)) or {}).get("refine")
        if info and info.get("portable") \
                and _manifest()["modules"][str(n)].get("lds_bytes", 0) \
                > self.max_shared_memory:
            return info["portable"]["file"]
        return "refine_%d.spv" % n

    def _peak_file(self, n, nbins, refine=False):
        general = self._refine_file(n) if refine else self._kernel_file(n)
        info = _manifest().get("modules", {}).get(str(n), {})
        if refine:
            info = info.get("refine", {})
        one = info.get("one_bin") if nbins == 1 else None
        if one:
            if general.endswith("_lds32.spv"):
                return one.get("portable", {}).get("file", general)
            return one["file"]
        return general

    def pipeline(self, n):
        """Build (and cache) the compute pipeline for transform length ``n``.

        Cached because creating a pipeline compiles the SPIR-V in the driver,
        which costs milliseconds -- far more than a dispatch -- and a batched
        workload calls this once and dispatches many times.
        """
        return self._build_pipeline(n, self._kernel_file(n), _NBIND, _PUSH_BYTES)

    def _kernel_file(self, n):
        """The fastest variant this device can actually run.

        Falls back to the 32 KB build when the preferred one asks for more
        shared memory than the device offers, rather than failing to create
        the pipeline on the user's machine.
        """
        info = _manifest().get("modules", {}).get(str(n))
        if info and info.get("local_size", [0])[0] > self.max_invocations:
            raise UnsupportedSize(
                "n=%d needs a %d-thread workgroup and this device allows %d; "
                "use a shorter transform or device='cpu'"
                % (n, info["local_size"][0], self.max_invocations))
        if info and info.get("lds_bytes", 0) > self.max_shared_memory:
            alt = info.get("portable")
            if alt is None:
                raise VulkanError(
                    "n=%d needs %d KB of workgroup memory and this device "
                    "offers %d KB" % (n, info["lds_bytes"] // 1024,
                                      self.max_shared_memory // 1024))
            return alt["file"]
        return "tierb_%d.spv" % n

    def _build_pipeline(self, key, filename, nbind, push_bytes):
        if key in self._pipelines:
            return self._pipelines[key]
        vk = self.vk
        blob = (_SPIRV / filename).read_bytes()
        code = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        sm_info = _ShaderModule(16, None, 0, len(blob), ctypes.cast(code, _vp))
        module = _vp()
        _check(vk.vkCreateShaderModule(self.device, ctypes.byref(sm_info), None,
                                       ctypes.byref(module)), "vkCreateShaderModule")

        bindings = (_LayoutBinding * nbind)(
            *[_LayoutBinding(i, _DESC_STORAGE_BUFFER, 1, _STAGE_COMPUTE, None)
              for i in range(nbind)])
        sl_info = _SetLayoutCreate(32, None, 0, nbind, bindings)
        set_layout = _vp()
        _check(vk.vkCreateDescriptorSetLayout(self.device, ctypes.byref(sl_info),
                                              None, ctypes.byref(set_layout)),
               "vkCreateDescriptorSetLayout")

        # The uniform entry-point parameters compile to PUSH CONSTANTS, not
        # to a descriptor. Taking that from the compiled module rather than
        # the source is the difference between working and binding a buffer
        # the shader never reads.
        push = _PushRange(_STAGE_COMPUTE, 0, push_bytes)
        layouts = (_vp * 1)(set_layout)
        pl_info = _PipelineLayoutCreate(30, None, 0, 1, ctypes.cast(layouts, _vp),
                                        1, ctypes.pointer(push))
        layout = _vp()
        _check(vk.vkCreatePipelineLayout(self.device, ctypes.byref(pl_info), None,
                                         ctypes.byref(layout)),
               "vkCreatePipelineLayout")

        stage = _StageCreate(18, None, 0, _STAGE_COMPUTE, module,
                             b"main", None)
        cp_info = _ComputePipelineCreate(29, None, 0, stage, layout, None, 0)
        pipe = _vp()
        _check(vk.vkCreateComputePipelines(self.device, None, 1,
                                           ctypes.byref(cp_info), None,
                                           ctypes.byref(pipe)),
               "vkCreateComputePipelines")
        vk.vkDestroyShaderModule(self.device, module, None)
        self._pipelines[key] = (pipe, layout, set_layout)
        return self._pipelines[key]

    def hier_peaks(self, n, band, data, tmpl, ct0, raw_thr,
                   binsize=None, threshold=0.0, window=None,
                   upload_data=True, upload_tmpl=True):
        """The whole hierarchical filter in ONE command buffer.

        Coarse correlation, survivor compaction, then listed refinement.
        Shared input uses a preceding GPU coarse-band extraction dispatch.
        The survivor count stays on the device through indirect dispatch.
        """
        vk = self.vk
        nd, nt = data.shape[0], tmpl.shape[0]
        lo, hi = (0, n) if window is None else (int(window[0]), int(window[1]))
        lo, hi = max(0, min(lo, n)), max(0, min(hi, n))
        if lo >= hi:
            raise ValueError("empty window (%d, %d)" % (lo, hi))
        binsize = n if binsize is None else int(binsize)
        nbins = -(-(hi - lo) // binsize)
        if nbins > _MAX_BINS:
            # Same split as peaks(): bins are contiguous in the window, so
            # cutting the window on a bin boundary cuts the bins exactly.
            span = _MAX_BINS * binsize
            pi, pv = [], []
            for a in range(lo, hi, span):
                bnd = min(a + span, hi)
                i2, v2 = self.hier_peaks(n, band, data, tmpl, ct0, raw_thr, binsize=binsize,
                                         threshold=threshold, window=(a, bnd),
                                         upload_data=upload_data,
                                         upload_tmpl=upload_tmpl)
                pi.append(i2); pv.append(v2)
                # The first piece invalidated all old resident copies. Do not
                # invalidate its fresh upload again on the remaining pieces.
                upload_data = upload_tmpl = False
            return np.concatenate(pi, axis=2), np.concatenate(pv, axis=2)
        shift = (binsize.bit_length() - 1) if binsize & (binsize - 1) == 0 else -1
        t2 = float(threshold) ** 2 if threshold > 0 else 0.0

        key = ("hier", n, band, nd, nt, nbins, binsize, shift, lo, hi,
               int(np.float32(t2).view(np.uint32)),
               float(raw_thr))
        key += (shared_key(data, self), shared_key(tmpl, self))
        storage_key = ("hier", n, band, nd, nt, nbins, *key[-2:])
        upload_data, upload_tmpl, dsig, tsig = self._input_uploads(
            storage_key, data, tmpl, upload_data, upload_tmpl)
        batch = self._hier.get(key)
        if batch is None:
            incoming = [b for b in (shared_buffer(data, self), shared_buffer(tmpl, self)) if b is not None]
            estimate = (8*n*(nd+nt) + 8*band*(nd+nt) + nd*nt*(16+12*nbins) + 12
                        - (nd*n*8 if shared_buffer(data, self) else 0)
                        - (nt*n*8 if shared_buffer(tmpl, self) else 0))
            if storage_key in self._storage:
                estimate = 0
            self._cache_room(estimate, incoming=incoming, keep_storage=storage_key)
            fresh = storage_key not in self._storage
            pool_start = len(getattr(self, '_pools', []))
            batch = self._make_hier(storage_key, n, band, nd, nt, nbins, binsize,
                                    shift, lo, hi, t2, raw_thr, data, tmpl)
            self._hier[key] = batch
            self._register_record('hier', key, storage_key, pool_start)
            if fresh:
                upload_data = upload_tmpl = True
        self._cache_touch('hier', key)
        bufs, cmd = batch
        # Upload only what changed. A template bank is 67 MB at n=16384 with
        # 512 templates, and re-sending it on every call dwarfed the
        # filtering it was feeding.
        if upload_data:
            write_input(bufs["data"], data)
            if shared_buffer(data, self) is not None:
                pass  # device band extraction is recorded before the coarse FFT
            elif _use_c16(band) and not _COARSE_TILE.get(band):
                bufs["cdata"].write(_pack_half2(data[:, :band]))
            else:
                bufs["cdata"].write(np.ascontiguousarray(data[:, :band], np.complex64))
            self._uploaded["data"][storage_key] = dsig
        if upload_tmpl:
            write_input(bufs["tmpl"], tmpl)
            if _use_c16(band) and not _COARSE_TILE.get(band):
                bufs["ct0"].write(_pack_half2(ct0))
            else:
                bufs["ct0"].write(np.ascontiguousarray(ct0, np.complex64))
            self._uploaded["tmpl"][storage_key] = tsig

        self._submit(cmd)

        out = nd * nt * nbins
        idx = bufs["idx"].read(np.int32, out).reshape(nd, nt, nbins)
        val = bufs["val"].read(np.float32, out * 2).view(
            np.complex64).reshape(nd, nt, nbins)
        self.last_refinements = int(bufs["args"].read(np.uint32, 1)[0])
        return idx, val

    def _descriptor_set(self, set_layout, bufs):
        vk = self.vk
        nbind = len(bufs)
        sizes = (_PoolSize * 1)(_PoolSize(_DESC_STORAGE_BUFFER, nbind))
        dp = _DescPoolCreate(33, None, 0, 1, 1, sizes)
        pool = _vp()
        _check(vk.vkCreateDescriptorPool(self.device, ctypes.byref(dp), None,
                                         ctypes.byref(pool)),
               "vkCreateDescriptorPool")
        self._pools = getattr(self, "_pools", [])
        self._pools.append(pool)
        layouts = (_vp * 1)(set_layout)
        da = _DescSetAlloc(34, None, pool, 1, ctypes.cast(layouts, _vp))
        dset = _vp()
        _check(vk.vkAllocateDescriptorSets(self.device, ctypes.byref(da),
                                           ctypes.byref(dset)),
               "vkAllocateDescriptorSets")
        infos = (_DescBufferInfo * nbind)(
            *[_DescBufferInfo(b.handle, 0, _WHOLE_SIZE) for b in bufs])
        writes = (_WriteDescSet * nbind)(*[
            _WriteDescSet(35, None, dset, i, 0, 1, _DESC_STORAGE_BUFFER, None,
                          ctypes.pointer(infos[i]), None) for i in range(nbind)])
        vk.vkUpdateDescriptorSets(self.device, nbind, writes, 0, None)
        return dset

    def _make_hier(self, key, n, band, nd, nt, nbins, binsize, shift, lo, hi,
                   t2, raw_thr, data=None, tmpl=None):
        vk = self.vk
        tile = _COARSE_TILE.get(band)
        _ppg = 1          # pairs per workgroup; raised only on the c16 path
        _tile = 1         # templates per tile; compiled into the kernel,
                          # so it is chosen with the kernel, not later
        if tile:
            cpipe, clayout, cset_layout = self._build_pipeline(
                ("coarse", band), "coarse_%d.spv" % band, 3, 8)
        elif not _use_c16(band):
            cpipe, clayout, cset_layout = self.pipeline(band)
        else:
            # The coarse ROLE, reading packed cdata/ct0. Not self.pipeline()
            # -- that is the flat filter's full-precision build of the same
            # entry, and handing it packed buffers makes it read 4-byte
            # elements as 8-byte ones: every peak comes back -1.
            # Four pairs per workgroup where the count allows it. A partial
            # group would index past the data buffer, so the fallback is not
            # optional -- it is what makes the fast build safe to ship.
            # Fill exactly one wave32 and no more. WG = band/16, so
            # PPG = 32/WG = 512/band. Measured at band 128 (WG 8): 1.911 ->
            # 0.932 ms, 2.05x. Beyond a full wave it does not pay -- band
            # 512 is already WG 32 and PPG 4 changed nothing there, while
            # band 1024 regressed 4.348 -> 5.006 as the per-group stage grew.
            # PPG = 512/band fills a wave32 where WG < 32. Safe now
            # that the peak reduction is per-pair (see tierb.slang): each
            # lane maxes into its own slot, so tiles cannot mix.
            _ppg = max(1, min(4, 512 // band))
            if (nd * nt) % _ppg:
                _ppg = 1          # a partial group would index past the data

            # TILE_T is COMPILED INTO the kernel, so it is part of kernel
            # identity and must be decided HERE, where the kernel is
            # chosen -- not at dispatch time, where the two could disagree.
            #
            # The tile walks TILE_T CONSECUTIVE TEMPLATES from one data
            # row, so ntemplates must divide by it. The pair count dividing
            # is NOT sufficient: nt=2 with tile=4 gives 4 % 4 == 0 while
            # the tile still runs past the end of the bank. Traced at
            # band 512: 4 groups at p0 = 0, 4, 8, 12 with only pairs 0 and
            # 1 reachable, so half the signals were dismissed -- and at
            # nt=4 the out-of-range groups WROTE past the output buffer.
            _tile = _COARSE_TILE_T.get(band, 1)
            if _tile > 1 and (nt % _tile or (nd * nt) % (_ppg * _tile)):
                _tile = 1

            cpipe, clayout, cset_layout = self._build_pipeline(
                ("coarse16", band, _ppg, _tile),
                "tierb_%d_c16%s%s.spv" % (band,
                    "p%d" % _ppg if _ppg > 1 else "",
                    "t%d" % _tile if _tile > 1 else ""),
                _NBIND, _PUSH_BYTES)
        # gatedTierB is NOT built. Its only caller was coarse_odd(), the
        # last remnant of the even/odd split, which was never invoked after
        # the odd half was removed -- so the kernel was compiled on every
        # plan and never dispatched. RADV_DEBUG=shaderstats showed it at 256
        # VGPRs with 18 SPILLED and 2304 bytes of scratch: the worst kernel
        # in the build, existing only to be compiled.
        kpipe, klayout, kset_layout = self._build_pipeline(
            "compact", "compact.spv", 5, 12)
        refine_file = self._peak_file(n, nbins, refine=True)
        rpipe, rlayout, rset_layout = self._build_pipeline(
            ("refine", refine_file), refine_file, 5, _PUSH_BYTES)
        pairs = nd * nt
        b = self._storage.get(key)
        if b is None:
            b = {
                "data":  shared_buffer(data, self) or _Buffer(self, nd * n * 8),
                "tmpl":  shared_buffer(tmpl, self) or _Buffer(self, nt * n * 8),
                "cdata": _Buffer(self, nd * band * (4 if _use_c16(band) and not tile else 8)),
                "ct0":   _Buffer(self, nt * band * (4 if _use_c16(band) and not tile else 8)),
                "cidx":  _Buffer(self, pairs * 4),
                "cval":  _Buffer(self, pairs * 8),
                # The compacted survivor list and the indirect group count.
                # args is [groupCountX, 1, 1]; compactPairs atomically bumps
                # [0], so the count never has to reach the host and this
                # stays one recorded command buffer.
                "surv":  _Buffer(self, pairs * 4),
                "args":  _Buffer(self, 12, usage=_BUF_STORAGE | _BUF_INDIRECT),
                "idx":   _Buffer(self, nd * nt * nbins * 4, readback=True),
                "val":   _Buffer(self, nd * nt * nbins * 8, readback=True),
            }
            self._storage[key] = b
        # The tiled coarse kernel reports a magnitude per pair and nothing
        # else -- a maximum does not depend on the output ordering, so it
        # needs no index and no digit reversal.
        if tile:
            ds_coarse = self._descriptor_set(cset_layout,
                                           [b["cdata"], b["ct0"], b["cval"]])
        else:
            ds_coarse = self._descriptor_set(cset_layout,
                                           [b["cdata"], b["ct0"], b["cidx"], b["cval"]])
        # The refine reads the EVEN buffer for both coarse inputs. The odd
        # half is gone -- the coarse grid is critically sampled and the even
        # series is the whole answer -- so binding eval twice makes the
        # kernel's `od` equal its `ev`, `best` reduce to `ev`, and its
        # two-test predicate collapse to one comparison. No kernel rebuild:
        # the shader already computes exactly this when the two buffers
        # agree, which is how the odd pass itself was implemented.
        ds_compact = self._descriptor_set(
            kset_layout, [b["cval"], b["surv"], b["args"],
                          b["idx"], b["val"]])
        ds_listed = self._descriptor_set(
            rset_layout,
            [b["data"], b["tmpl"], b["idx"], b["val"], b["surv"]])

        shared_data = shared_buffer(data, self) is not None
        if shared_data:
            ppipe, playout, psl = self._build_pipeline(
                "pack_coarse", "pack_coarse.spv", 2, 16)
            ds_pack = self._descriptor_set(psl, [b["data"], b["cdata"]])

        cb = _CmdBufAlloc(40, None, self.command_pool, 0, 1)
        cmd = _vp()
        _check(vk.vkAllocateCommandBuffers(self.device, ctypes.byref(cb),
                                           ctypes.byref(cmd)),
               "vkAllocateCommandBuffers")
        _check(vk.vkBeginCommandBuffer(cmd, ctypes.byref(
            _CmdBufBegin(42, None, 0, None))), "vkBeginCommandBuffer")

        def coarse(ds):
            vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, cpipe)
            sets = (_vp * 1)(ds)
            vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, clayout, 0, 1,
                                       sets, 0, None)
            if tile:
                pc = (ctypes.c_uint32 * 2)(nt, pairs)
                vk.vkCmdPushConstants(cmd, clayout, _STAGE_COMPUTE, 0, 8,
                                      ctypes.byref(pc))
                vk.vkCmdDispatch(cmd, (pairs + tile - 1) // tile, 1, 1)
            else:
                # One bin over the whole coarse span: the reported peak IS
                # the maximum, which is what the gate needs.
                pc = (ctypes.c_uint32 * 7)(nt, 0, band, band,
                                           band.bit_length() - 1, 1, 0)
                vk.vkCmdPushConstants(cmd, clayout, _STAGE_COMPUTE, 0,
                                      _PUSH_BYTES, ctypes.byref(pc))
                # PPG pairs per workgroup and TILE_T templates per pair,
                # so PPG*TILE_T times fewer groups.
                #
                # _tile is the one the KERNEL was compiled with -- it is
                # chosen where the pipeline is chosen. Recomputing it here
                # is what let the two disagree: the kernel carried tile 4
                # while this dispatched for tile 1.
                vk.vkCmdDispatch(cmd, pairs // (_ppg * _tile), 1, 1)

        def barrier():
            mb = _MemBarrier(46, None, _ACCESS_SHADER_WRITE, _ACCESS_SHADER_READ)
            vk.vkCmdPipelineBarrier(cmd, _STAGE_COMPUTE_BIT, _STAGE_COMPUTE_BIT,
                                    0, 1, ctypes.byref(mb), 0, None, 0, None)

        # Pairs that do not survive are never visited now, so their -1 has
        # to be written up front rather than by a workgroup that launches
        # only to exit. That is the whole saving: 1.394 ms at 512x512.
        # Only the twelve bytes of args. The output needs no clear: the
        # compaction kernel walks every pair and writes the -1 for the ones
        # it dismisses, so filling 3 MB here would only be overwriting
        # slots the refine is about to fill anyway.
        vk.vkCmdFillBuffer(cmd, b["args"].handle, 0, 4, 0)   # count starts at 0
        vk.vkCmdFillBuffer(cmd, b["args"].handle, 4, 8, 1)   # y = z = 1
        barrier()

        if shared_data:
            vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, ppipe)
            sets = (_vp * 1)(ds_pack)
            vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, playout,
                                      0, 1, sets, 0, None)
            pc = (ctypes.c_uint32 * 4)(n, band, nd*band,
                                      int(_use_c16(band) and not tile))
            vk.vkCmdPushConstants(cmd, playout, _STAGE_COMPUTE, 0, 16,
                                  ctypes.byref(pc))
            vk.vkCmdDispatch(cmd, (nd*band + 255)//256, 1, 1)
            barrier()

        coarse(ds_coarse)
        barrier()

        vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, kpipe)
        sets = (_vp * 1)(ds_compact)
        vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, klayout, 0, 1,
                                   sets, 0, None)
        kpc = (ctypes.c_uint32 * 3)(
            pairs, int(np.float32(raw_thr).view(np.uint32)), nbins)
        vk.vkCmdPushConstants(cmd, klayout, _STAGE_COMPUTE, 0, 12,
                              ctypes.byref(kpc))
        vk.vkCmdDispatch(cmd, (pairs + 255) // 256, 1, 1)
        barrier()

        vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, rpipe)
        sets = (_vp * 1)(ds_listed)
        vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, rlayout, 0, 1,
                                   sets, 0, None)
        pc = (ctypes.c_uint32 * 7)(
            nt, lo, hi, binsize, shift & 0xFFFFFFFF, nbins,
            int(np.float32(t2).view(np.uint32)))
        vk.vkCmdPushConstants(cmd, rlayout, _STAGE_COMPUTE, 0,
                              _PUSH_BYTES, ctypes.byref(pc))
        vk.vkCmdDispatchIndirect(cmd, b["args"].handle, 0)
        _check(vk.vkEndCommandBuffer(cmd), "vkEndCommandBuffer")
        return b, cmd

    def empty_shared(self, shape, dtype=np.complex64):
        return empty_shared(self, _Buffer, shape, dtype)

    def forward(self, n, series, starts, spectra, *, defer=False):
        """Gather and normalize forward FFTs directly into shared spectra."""
        vk = self.vk
        pipe, layout, sl = self._build_pipeline(
            ("forward", n), "forward_%d.spv" % n, 3, 4)
        buffers = [shared_buffer(a, self) for a in (series, starts, spectra)]
        if any(b is None for b in buffers):
            raise ValueError("forward buffers must belong to this GPU context")
        key = (n, series.size, spectra.shape[0],
               *(a.ctypes.data for a in (series, starts, spectra)))
        forwards = getattr(self, "_forwards", None)
        if forwards is None:
            forwards = self._forwards = {}
        batch = forwards.get(key)
        if batch is None:
            self._cache_room(0, incoming=buffers)
            pool_start = len(getattr(self, '_pools', []))
            ds = self._descriptor_set(sl, buffers)
            cmd = _vp()
            info = _CmdBufAlloc(40, None, self.command_pool, 0, 1)
            _check(vk.vkAllocateCommandBuffers(self.device, ctypes.byref(info),
                                               ctypes.byref(cmd)), "allocate forward")
            begin = _CmdBufBegin(42, None, 0, None)
            _check(vk.vkBeginCommandBuffer(cmd, ctypes.byref(begin)), "begin forward")
            vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, pipe)
            sets = (_vp * 1)(ds)
            vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, layout, 0, 1,
                                      sets, 0, None)
            params = _u32(series.size)
            vk.vkCmdPushConstants(cmd, layout, _STAGE_COMPUTE, 0, 4,
                                  ctypes.byref(params))
            vk.vkCmdDispatch(cmd, spectra.shape[0], 1, 1)
            # Publish FFT stores to later compute dispatches and mapped host
            # readers. Queue completion alone is not a shader memory barrier.
            mb = _MemBarrier(46, None, _ACCESS_SHADER_WRITE,
                             _ACCESS_SHADER_READ | 0x2000)  # HOST_READ
            vk.vkCmdPipelineBarrier(cmd, _STAGE_COMPUTE_BIT,
                                    _STAGE_COMPUTE_BIT | 0x4000,  # HOST
                                    0, 1, ctypes.byref(mb), 0, None, 0, None)
            _check(vk.vkEndCommandBuffer(cmd), "end forward")
            batch = (*buffers, cmd)
            forwards[key] = batch
            self._register_record('forward', key, None, pool_start)
        self._cache_touch('forward', key)
        cmd = batch[-1]
        if defer:
            self._pending_forward = cmd
        else:
            self._submit(cmd)

    def cancel_forward(self):
        self._pending_forward = None

    def _submit(self, cmd):
        """Forward and correlation share one submit and completion wait."""
        pending = getattr(self, "_pending_forward", None)
        commands = ([pending] if pending is not None else [])
        if cmd is not None:
            commands.append(cmd)
        self._pending_forward = None
        if not commands:
            return
        cmds = (_vp * len(commands))(*commands)
        submit = _SubmitInfo(4, None, 0, None, None, len(commands), cmds, 0, None)
        _check(self.vk.vkQueueSubmit(self.queue, 1, ctypes.byref(submit), None),
               "vkQueueSubmit")
        _check(self.vk.vkQueueWaitIdle(self.queue), "vkQueueWaitIdle")

    def _make_batch(self, key, n, nd, nt, nbins, binsize, shift, lo, hi, t2, data=None, tmpl=None):
        """Buffers, descriptor set and a recorded command buffer for one shape."""
        vk = self.vk
        filename = self._peak_file(n, nbins)
        pipe, layout, set_layout = self._build_pipeline(
            ("peaks", filename), filename, _NBIND, _PUSH_BYTES)
        out = nd * nt * nbins
        bufs = self._storage.get(key)
        if bufs is None:
            bufs = (shared_buffer(data, self) or _Buffer(self, nd * n * 8),
                    shared_buffer(tmpl, self) or _Buffer(self, nt * n * 8),
                    _Buffer(self, out * 4, readback=True),
                    _Buffer(self, out * 8, readback=True))
            self._storage[key] = bufs
        b_data, b_tmpl, b_idx, b_val = bufs
        dset = self._descriptor_set(set_layout, bufs)

        cb_info = _CmdBufAlloc(40, None, self.command_pool, 0, 1)
        cmd = _vp()
        _check(vk.vkAllocateCommandBuffers(self.device, ctypes.byref(cb_info),
                                           ctypes.byref(cmd)),
               "vkAllocateCommandBuffers")
        # NOT one-time-submit: this recording is replayed on every call.
        begin = _CmdBufBegin(42, None, 0, None)
        _check(vk.vkBeginCommandBuffer(cmd, ctypes.byref(begin)),
               "vkBeginCommandBuffer")
        vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, pipe)
        sets = (_vp * 1)(dset)
        vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, layout, 0, 1,
                                   sets, 0, None)
        pc = (ctypes.c_uint32 * 7)(
            nt, lo, hi, binsize, shift & 0xFFFFFFFF, nbins,
            int(np.float32(t2).view(np.uint32)))
        vk.vkCmdPushConstants(cmd, layout, _STAGE_COMPUTE, 0, _PUSH_BYTES,
                              ctypes.byref(pc))
        vk.vkCmdDispatch(cmd, nd * nt, 1, 1)
        _check(vk.vkEndCommandBuffer(cmd), "vkEndCommandBuffer")
        return (b_data, b_tmpl, b_idx, b_val, cmd)

    def peaks(self, n, data, tmpl, binsize=None, threshold=0.0, window=None,
              upload_data=True, upload_tmpl=True):
        """Peak index and complex value per (data, template, bin).

        Mirrors MatchedFilter.run: bins are ``ceil((end-start)/binsize)``
        counted from ``start``, and a bin whose maximum does not exceed
        ``threshold`` comes back with index -1 and a zero value.  No
        magnitude is produced anywhere -- it is ``abs(value)``.
        """
        vk = self.vk
        nd, nt = data.shape[0], tmpl.shape[0]
        lo, hi = (0, n) if window is None else (int(window[0]), int(window[1]))
        lo = max(0, min(lo, n))
        hi = max(0, min(hi, n))
        if lo >= hi:
            raise ValueError("empty window (%d, %d)" % (lo, hi))
        binsize = n if binsize is None else int(binsize)
        if binsize < 1:
            raise ValueError("binsize must be >= 1")
        nbins = -(-(hi - lo) // binsize)
        if nbins > _MAX_BINS:
            # The per-bin table lives in shared memory and holds _MAX_BINS
            # entries. Bins are contiguous in the window, so splitting the
            # WINDOW on a bin boundary splits the bins exactly -- each piece
            # is an ordinary call and the results concatenate. No kernel
            # change, and no limit left to explain to a caller.
            span = _MAX_BINS * binsize
            parts_i, parts_v = [], []
            for start in range(lo, hi, span):
                stop = min(start + span, hi)
                pi, pv = self.peaks(n, data, tmpl, binsize=binsize,
                                    threshold=threshold, window=(start, stop),
                                    upload_data=upload_data,
                                    upload_tmpl=upload_tmpl)
                parts_i.append(pi)
                parts_v.append(pv)
                upload_data = upload_tmpl = False
            return (np.concatenate(parts_i, axis=2),
                    np.concatenate(parts_v, axis=2))
        # Shift when the binsize is a power of two, divide when it is not --
        # the same split the CPU makes, and why no restriction is needed.
        shift = (binsize.bit_length() - 1) if binsize & (binsize - 1) == 0 else -1
        t2 = float(threshold) ** 2 if threshold > 0 else 0.0

        # Everything below the data itself is REUSED across calls. Rebuilding
        # it cost 0.5 ms of the 0.65 ms a 1024-pair call took: buffers,
        # descriptor pool and set, and the recorded command buffer. With them
        # cached a call is a host copy, a submit and a read -- 0.14 ms, of
        # which the dispatch is 0.07.
        #
        # The key carries the push constants because they are RECORDED into
        # the command buffer. A call that changes the threshold or the window
        # gets its own recording rather than silently running the previous
        # one, which would be wrong rather than slow.
        key = (n, nd, nt, nbins, binsize, shift, lo, hi,
               int(np.float32(t2).view(np.uint32)))
        key += (shared_key(data, self), shared_key(tmpl, self))
        storage_key = ("flat", n, nd, nt, nbins, *key[-2:])
        upload_data, upload_tmpl, dsig, tsig = self._input_uploads(
            storage_key, data, tmpl, upload_data, upload_tmpl)
        batch = self._batches.get(key)
        if batch is None:
            incoming = [b for b in (shared_buffer(data, self), shared_buffer(tmpl, self)) if b is not None]
            estimate = (8*n*(nd+nt) + 12*nd*nt*nbins
                        - (nd*n*8 if shared_buffer(data, self) else 0)
                        - (nt*n*8 if shared_buffer(tmpl, self) else 0))
            if storage_key in self._storage:
                estimate = 0
            self._cache_room(estimate, incoming=incoming, keep_storage=storage_key)
            fresh = storage_key not in self._storage
            pool_start = len(getattr(self, '_pools', []))
            batch = self._make_batch(storage_key, n, nd, nt, nbins,
                                     binsize, shift, lo, hi, t2, data, tmpl)
            self._batches[key] = batch
            self._register_record('flat', key, storage_key, pool_start)
            if fresh:
                upload_data = upload_tmpl = True
        self._cache_touch('flat', key)
        b_data, b_tmpl, b_idx, b_val, cmd = batch

        if upload_data:
            write_input(b_data, data)
            self._uploaded["data"][storage_key] = dsig
        if upload_tmpl:
            write_input(b_tmpl, tmpl)
            self._uploaded["tmpl"][storage_key] = tsig

        self._submit(cmd)

        out = nd * nt * nbins
        # int32 as the kernel wrote it. The caller's PEAK_DTYPE index is
        # int64, and assigning int32 into that field widens it during the
        # strided write that has to happen anyway -- so converting here
        # first is a whole extra pass over the output and a whole extra
        # allocation, for nothing. Measured at 65536 pairs: the host side of
        # a call was 0.168 ms, five passes over 0.79 MB.
        idx = b_idx.read(np.int32, out).reshape(nd, nt, nbins)
        val = b_val.read(np.float32, out * 2).view(
            np.complex64).reshape(nd, nt, nbins)
        return idx, val

    cache_limit_recordings = 256

    def _register_record(self, kind, key, storage, pool_start):
        token = (kind, key)
        self._record_pools[token] = self._pools[pool_start:]
        if storage is not None:
            self._record_storage[token] = storage
            self._storage_users.setdefault(storage, set()).add(token)

    def _drop_storage(self, key):
        buffers = self._storage.pop(key)
        for buf in (buffers.values() if isinstance(buffers, dict) else buffers):
            buf.destroy()
        self._storage_users.pop(key, None)
        for resident in self._uploaded.values():
            resident.pop(key, None)

    def _evict_record(self, kind, key, keep_storage=None):
        token = (kind, key)
        cache = {'flat': self._batches, 'hier': self._hier,
                 'forward': getattr(self, '_forwards', {})}[kind]
        batch = cache.pop(key)
        cmd = batch[-1]
        if getattr(self, '_pending_forward', None) is cmd:
            self._submit(None)
        commands = (_vp * 1)(cmd)
        self.vk.vkFreeCommandBuffers.argtypes = [_vp, _vp, _u32, ctypes.POINTER(_vp)]
        self.vk.vkFreeCommandBuffers(self.device, self.command_pool, 1, commands)
        pools = self._record_pools.pop(token, [])
        for pool in pools:
            self.vk.vkDestroyDescriptorPool(self.device, pool, None)
        dead = {pool.value for pool in pools}
        self._pools = [pool for pool in self._pools if pool.value not in dead]
        storage = self._record_storage.pop(token, None)
        if storage is not None:
            users = self._storage_users[storage]
            users.discard(token)
            if not users and storage != keep_storage:
                self._drop_storage(storage)

    def clear_cache(self):
        """Release records and owned storage, preserving external shared arrays."""
        self._submit(None)
        for kind, cache in (('flat', self._batches), ('hier', self._hier),
                            ('forward', getattr(self, '_forwards', {}))):
            for key in list(cache):
                self._evict_record(kind, key)
        # Also clean up storage/descriptors left by failed construction.
        for key in list(self._storage):
            self._drop_storage(key)
        for pool in getattr(self, '_pools', []):
            self.vk.vkDestroyDescriptorPool(self.device, pool, None)
        self._pools = []
        self._cache_order = {}
        self._uploaded = {"data": {}, "tmpl": {}}

    def destroy(self):
        if getattr(self, "device", None) is None:
            return
        self.clear_cache()
        vk = self.vk
        for pipe, layout, set_layout in self._pipelines.values():
            vk.vkDestroyPipeline(self.device, pipe, None)
            vk.vkDestroyPipelineLayout(self.device, layout, None)
            vk.vkDestroyDescriptorSetLayout(self.device, set_layout, None)
        self._pipelines.clear()
        vk.vkDestroyCommandPool(self.device, self.command_pool, None)
        vk.vkDestroyDevice(self.device, None)
        vk.vkDestroyInstance(self.instance, None)
        self.device = None
        self.instance = None

    def __del__(self):
        """A context that goes out of scope must give the device back.

        Nothing called destroy() unless a caller did so by hand, so every
        MatchedFilter(device="gpu") that was simply dropped leaked its
        instance and device -- a few file descriptors each. A process that
        builds many then walks into RLIMIT_NOFILE, which Fedora ships at 1024.

        What makes this worth a comment is how it presents. The fd exhaustion
        surfaces as Mesa failing to create an anonymous file for its
        allocations, vkCreateInstance returning VK_ERROR_INCOMPATIBLE_DRIVER,
        and the GPU disappearing from enumeration mid-session -- so the
        machine looks like it has a broken driver, and the tests report
        dozens of failures that name everything except the cause. Measured on
        this box the suite leaked 540 descriptors across 108 tests.

        Exceptions are swallowed: this can run during interpreter shutdown,
        and a finalizer that raises there is noise nobody can act on.
        """
        try:
            self.destroy()
        except Exception:
            pass
