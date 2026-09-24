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

_SPIRV = pathlib.Path(__file__).resolve().parent / "spirv"

# --- enough of the Vulkan enums to dispatch -------------------------------
_QUEUE_COMPUTE = 0x2
_BUF_STORAGE = 0x20
_MEM_DEVICE_LOCAL, _MEM_HOST_VISIBLE, _MEM_HOST_COHERENT = 0x1, 0x2, 0x4
_DESC_STORAGE_BUFFER = 7
_STAGE_COMPUTE = 0x20
_BIND_POINT_COMPUTE = 1
_ONE_TIME_SUBMIT = 0x1
_WHOLE_SIZE = 0xFFFFFFFFFFFFFFFF

_u32, _u64, _vp = ctypes.c_uint32, ctypes.c_uint64, ctypes.c_void_p


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

    def __init__(self, ctx, nbytes):
        self.ctx, self.nbytes = ctx, max(int(nbytes), 4)
        vk = ctx.vk
        info = _BufferCreate(12, None, 0, self.nbytes, _BUF_STORAGE, 0, 0, None)
        self.handle = _vp()
        _check(vk.vkCreateBuffer(ctx.device, ctypes.byref(info), None,
                                 ctypes.byref(self.handle)), "vkCreateBuffer")
        req = _MemReq()
        vk.vkGetBufferMemoryRequirements(ctx.device, self.handle, ctypes.byref(req))
        alloc = _MemAlloc(5, None, req.size, ctx.memory_type(req.memoryTypeBits))
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
            vk.vkFreeMemory(dev, self.memory, None)
            vk.vkDestroyBuffer(dev, self.handle, None)
            self.handle = None


class Context:
    """One Vulkan device, its compute queue, and the pipelines built on it."""

    def __init__(self, index=0):
        vk, err = _vulkan._load()
        if vk is None:
            raise VulkanError(err)
        self.vk = vk
        self._pipelines = {}

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

    def memory_type(self, allowed_bits):
        """Prefer device-local host-visible memory; require host-visible."""
        want = _MEM_HOST_VISIBLE | _MEM_HOST_COHERENT
        for require in (want | _MEM_DEVICE_LOCAL, want):
            for i in range(self.mem_props.memoryTypeCount):
                flags = self.mem_props.memoryTypes[i].propertyFlags
                if allowed_bits & (1 << i) and (flags & require) == require:
                    return i
        raise VulkanError("no host-visible memory type available")

    # ---- pipeline ---------------------------------------------------------
    def pipeline(self, n):
        """Build (and cache) the compute pipeline for transform length ``n``.

        Cached because creating a pipeline compiles the SPIR-V in the driver,
        which costs milliseconds -- far more than a dispatch -- and a batched
        workload calls this once and dispatches many times.
        """
        if n in self._pipelines:
            return self._pipelines[n]
        vk = self.vk
        blob = (_SPIRV / ("tierb_%d.spv" % n)).read_bytes()
        code = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        sm_info = _ShaderModule(16, None, 0, len(blob), ctypes.cast(code, _vp))
        module = _vp()
        _check(vk.vkCreateShaderModule(self.device, ctypes.byref(sm_info), None,
                                       ctypes.byref(module)), "vkCreateShaderModule")

        bindings = (_LayoutBinding * 3)(
            *[_LayoutBinding(i, _DESC_STORAGE_BUFFER, 1, _STAGE_COMPUTE, None)
              for i in range(3)])
        sl_info = _SetLayoutCreate(32, None, 0, 3, bindings)
        set_layout = _vp()
        _check(vk.vkCreateDescriptorSetLayout(self.device, ctypes.byref(sl_info),
                                              None, ctypes.byref(set_layout)),
               "vkCreateDescriptorSetLayout")

        # `uniform uint ntmpl` compiles to a push constant, not a descriptor.
        push = _PushRange(_STAGE_COMPUTE, 0, 4)
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
        self._pipelines[n] = (pipe, layout, set_layout)
        return self._pipelines[n]

    def peaks(self, n, data, tmpl):
        """Peak magnitude per (data, template) pair.  Mirrors the CPU result."""
        vk = self.vk
        nd, nt = data.shape[0], tmpl.shape[0]
        pipe, layout, set_layout = self.pipeline(n)

        b_data = _Buffer(self, data.size * 8)
        b_tmpl = _Buffer(self, tmpl.size * 8)
        b_peak = _Buffer(self, nd * nt * 4)
        try:
            b_data.write(np.ascontiguousarray(data, np.complex64))
            b_tmpl.write(np.ascontiguousarray(tmpl, np.complex64))

            sizes = (_PoolSize * 1)(_PoolSize(_DESC_STORAGE_BUFFER, 3))
            dp_info = _DescPoolCreate(33, None, 0, 1, 1, sizes)
            pool = _vp()
            _check(vk.vkCreateDescriptorPool(self.device, ctypes.byref(dp_info),
                                             None, ctypes.byref(pool)),
                   "vkCreateDescriptorPool")
            try:
                set_layouts = (_vp * 1)(set_layout)
                ds_info = _DescSetAlloc(34, None, pool, 1,
                                        ctypes.cast(set_layouts, _vp))
                dset = _vp()
                _check(vk.vkAllocateDescriptorSets(self.device,
                                                   ctypes.byref(ds_info),
                                                   ctypes.byref(dset)),
                       "vkAllocateDescriptorSets")

                infos = (_DescBufferInfo * 3)(
                    _DescBufferInfo(b_data.handle, 0, _WHOLE_SIZE),
                    _DescBufferInfo(b_tmpl.handle, 0, _WHOLE_SIZE),
                    _DescBufferInfo(b_peak.handle, 0, _WHOLE_SIZE))
                writes = (_WriteDescSet * 3)(*[
                    _WriteDescSet(35, None, dset, i, 0, 1, _DESC_STORAGE_BUFFER,
                                  None, ctypes.pointer(infos[i]), None)
                    for i in range(3)])
                vk.vkUpdateDescriptorSets(self.device, 3, writes, 0, None)

                cb_info = _CmdBufAlloc(40, None, self.command_pool, 0, 1)
                cmd = _vp()
                _check(vk.vkAllocateCommandBuffers(self.device,
                                                   ctypes.byref(cb_info),
                                                   ctypes.byref(cmd)),
                       "vkAllocateCommandBuffers")
                begin = _CmdBufBegin(42, None, _ONE_TIME_SUBMIT, None)
                _check(vk.vkBeginCommandBuffer(cmd, ctypes.byref(begin)),
                       "vkBeginCommandBuffer")
                vk.vkCmdBindPipeline(cmd, _BIND_POINT_COMPUTE, pipe)
                sets = (_vp * 1)(dset)
                vk.vkCmdBindDescriptorSets(cmd, _BIND_POINT_COMPUTE, layout, 0, 1,
                                           sets, 0, None)
                ntmpl = _u32(nt)
                vk.vkCmdPushConstants(cmd, layout, _STAGE_COMPUTE, 0, 4,
                                      ctypes.byref(ntmpl))
                # one workgroup per (data, template) pair
                vk.vkCmdDispatch(cmd, nd * nt, 1, 1)
                _check(vk.vkEndCommandBuffer(cmd), "vkEndCommandBuffer")

                cmds = (_vp * 1)(cmd)
                submit = _SubmitInfo(4, None, 0, None, None, 1, cmds, 0, None)
                _check(vk.vkQueueSubmit(self.queue, 1, ctypes.byref(submit), None),
                       "vkQueueSubmit")
                _check(vk.vkQueueWaitIdle(self.queue), "vkQueueWaitIdle")
                vk.vkFreeCommandBuffers(self.device, self.command_pool, 1, cmds)
            finally:
                vk.vkDestroyDescriptorPool(self.device, pool, None)
            return b_peak.read(np.float32, nd * nt).reshape(nd, nt)
        finally:
            for buf in (b_data, b_tmpl, b_peak):
                buf.destroy()

    def destroy(self):
        vk = self.vk
        for pipe, layout, set_layout in self._pipelines.values():
            vk.vkDestroyPipeline(self.device, pipe, None)
            vk.vkDestroyPipelineLayout(self.device, layout, None)
            vk.vkDestroyDescriptorSetLayout(self.device, set_layout, None)
        self._pipelines.clear()
        vk.vkDestroyCommandPool(self.device, self.command_pool, None)
        vk.vkDestroyDevice(self.device, None)
        vk.vkDestroyInstance(self.instance, None)
