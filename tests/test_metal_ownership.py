"""Owned Objective-C references are balanced on success, failure and teardown."""
from collections import Counter
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from matchedfilter import _mtlcompute as M


class ObjC:
    def __init__(self, fail=None, limits=(1024, 1024)):
        self.refs = Counter({1: 1, 2: 1})  # device, queue
        self.fail = fail
        self.limits = limits
        self.pools = 0
        self.objc = SimpleNamespace(objc_getClass=lambda name: 90)

    @contextmanager
    def autorelease_pool(self):
        self.pools += 1
        try:
            yield
        finally:
            self.pools -= 1

    def nsstring(self, text):
        return 91

    def new(self, obj):
        self.refs[obj] += 1
        return obj

    def call(self, obj, selector, **kw):
        if selector == b'release':
            self.refs[obj] -= 1
            assert self.refs[obj] >= 0, 'double release'
        elif selector == b'alloc':
            return self.new(6)
        elif selector == b'init':
            return obj
        elif selector == b'newFunctionWithName:':
            return None if self.fail == 'function' else self.new(4)
        elif selector == b'newComputePipelineStateWithFunction:error:':
            return None if self.fail == 'pipeline' else self.new(5)
        elif selector == b'newComputePipelineStateWithDescriptor:options:reflection:error:':
            return None if self.fail == 'fallback' else self.new(7)
        elif selector == b'maxTotalThreadsPerThreadgroup':
            return self.limits[obj == 7]
        return None


def context(fail=None, limits=(1024, 1024)):
    c = M.Context.__new__(M.Context)
    c.o = ObjC(fail, limits)
    c.device, c.queue, c.name = 1, 2, 'fake'
    c._pipelines, c._batches, c._hier = {}, {}, {}
    c._stem = lambda *args: 'test'
    c._library = lambda stem: c.o.new(3)
    c._error = lambda err: 'injected failure'
    return c


@pytest.mark.parametrize('fail,limits', [
    (None, (1024, 1024)), (None, (32, 1024)),
    ('function', (1024, 1024)), ('pipeline', (1024, 1024)),
    ('fallback', (32, 1024)), (None, (32, 32))])
def test_pipeline_ownership(fail, limits):
    c = context(fail, limits)
    if fail or limits == (32, 32):
        with pytest.raises((M.MetalError, M.UnsupportedSize)):
            c.pipeline(1024)
    else:
        pipeline = c.pipeline(1024)
        assert c.pipeline(1024) == pipeline  # cache owns exactly one reference
        assert c.o.refs[pipeline] == 1
    assert c.o.pools == 0
    c.destroy()
    c.destroy()
    assert not +c.o.refs


def test_pending_forward_ownership_is_released():
    c = context()
    c._pending_metal = (c.o.new(8), [])
    c._forward_inflight = (c.o.new(9), [])
    c.destroy()
    assert not +c.o.refs


def test_device_enumeration_releases_array_and_returns_owned_handles(monkeypatch):
    from matchedfilter import _metal
    refs = Counter({100: 1, 101: 1, 102: 1})  # array retains its devices

    def message(obj, selector, *args):
        if selector == b'count':
            return 2
        if selector == b'objectAtIndex:':
            return [101, 102][args[0]]
        if selector == b'retain':
            refs[obj] += 1
        if selector == b'release':
            refs[obj] -= 1
            if obj == 100:
                refs[101] -= 1
                refs[102] -= 1
        return obj

    objc = SimpleNamespace(objc_msgSend=message, sel_registerName=lambda name: name)
    metal = SimpleNamespace(MTLCopyAllDevices=lambda: 100)
    monkeypatch.setattr(_metal.ctypes, 'cast', lambda fn, signature: fn)
    handles = _metal._all_devices(objc, metal)
    assert handles == [101, 102]
    assert refs == Counter({101: 1, 102: 1})
    for handle in handles:
        message(handle, b'release')
    assert not +refs


def test_metal_repeated_create_dispatch_destroy():
    import sys
    import numpy as np
    if sys.platform != 'darwin':
        pytest.skip('requires Metal')
    from matchedfilter import _metal
    devices, reason = _metal.enumerate_devices()
    if not devices:
        pytest.skip(reason or 'no Metal device')
    for _ in range(8):
        c = M.Context()
        try:
            bank = np.ones((1, 1024), np.complex64)
            index, value = c.peaks(1024, bank, bank)
            assert index.item() == 0
            np.testing.assert_allclose(value.item(), 1024)
        finally:
            c.destroy()
            c.destroy()
