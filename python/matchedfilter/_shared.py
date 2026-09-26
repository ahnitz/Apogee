"""Host-visible GPU allocations, with NumPy/DLPack lifetime ownership.

These arrays export CPU DLPack: a Vulkan/Metal allocation is not a CUDA or
ROCm allocation. Consumers must finish writing before a synchronous filter call.
"""
import ctypes
import weakref
import numpy as np

_allocations = weakref.WeakValueDictionary()


class _Allocation:
    def __init__(self, buffer):
        self.buffer = buffer
        _allocations[int(buffer.ptr.value if hasattr(buffer.ptr, 'value')
                         else buffer.ptr)] = self

    def __del__(self):
        buf = self.buffer
        if getattr(buf.ctx, 'device', None):
            buf.destroy()


class _Borrowed:
    """A descriptor reference; cache eviction must not free its allocation."""
    def __init__(self, allocation):
        self.owner = allocation
        self.handle = allocation.buffer.handle
        self.nbytes = allocation.buffer.nbytes
        self.ptr = allocation.buffer.ptr

    def write(self, array):
        pointer = self.ptr.value if hasattr(self.ptr, 'value') else self.ptr
        if array.ctypes.data != pointer:
            raise ValueError('shared input allocation changed during dispatch')

    def destroy(self):
        pass


def shared_buffer(array, ctx):
    """Recognize a contiguous prefix, including through host DLPack imports."""
    if not isinstance(array, np.ndarray) or not array.flags.c_contiguous:
        return None
    allocation = _allocations.get(array.ctypes.data)
    if (allocation is None or allocation.buffer.ctx is not ctx
            or array.nbytes > allocation.buffer.nbytes):
        return None
    return _Borrowed(allocation)


def shared_key(array, ctx):
    buf = shared_buffer(array, ctx)
    return array.ctypes.data if buf is not None else None


def empty_shared(ctx, buffer_type, shape, dtype=np.complex64):
    dtype = np.dtype(dtype)
    if dtype.hasobject:
        raise TypeError('shared arrays cannot contain Python objects')
    # NumPy validates dimensions and overflow before allocating GPU memory.
    shape = tuple(shape) if np.iterable(shape) else (shape,)
    probe = np.empty(shape, dtype=np.dtype('V0'))
    count = probe.size
    if count > np.iinfo(np.intp).max // max(dtype.itemsize, 1):
        raise ValueError('shared array is too large')
    nbytes = count * dtype.itemsize
    buf = buffer_type(ctx, nbytes)
    owner = _Allocation(buf)
    address = buf.ptr.value if hasattr(buf.ptr, 'value') else buf.ptr
    storage = (ctypes.c_ubyte * nbytes).from_address(address)
    storage._allocation = owner
    return np.ndarray(shape, dtype=dtype, buffer=storage)


def write_input(buffer, array):
    # Shared allocations already satisfy the dtype/layout contract. Do not
    # coerce them again: a prepared FFT may not have been submitted yet.
    if isinstance(buffer, _Borrowed):
        buffer.write(array)
    else:
        buffer.write(np.ascontiguousarray(array, np.complex64))
