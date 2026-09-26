"""Cache budgets count physical allocations and evict only enough LRU entries."""
from types import SimpleNamespace
from matchedfilter._gpu_cache import InputUploads


class Cache(InputUploads):
    def __init__(self):
        self._batches = {}
        self._hier = {}
        self.evicted = []

    def _evict_record(self, kind, key, keep_storage=None):
        self.evicted.append(key)
        self._batches.pop(key)


def test_shared_allocation_counted_once_including_incoming_prefix():
    c = Cache()
    physical = SimpleNamespace(nbytes=4096)
    owner = SimpleNamespace(buffer=physical)
    a, b = SimpleNamespace(owner=owner), SimpleNamespace(owner=owner)
    c._batches = {0:(a, SimpleNamespace(nbytes=16)), 1:(b, SimpleNamespace(nbytes=32))}
    assert c._cache_bytes((SimpleNamespace(owner=owner),)) == 4096+16+32


def test_lru_preserves_recent_records_and_incoming_budget():
    c = Cache()
    for i in range(3):
        c._batches[i] = (SimpleNamespace(nbytes=100),)
        c._cache_touch('flat',i)
    c._cache_touch('flat',0)
    c.cache_limit_bytes = 350
    c._cache_room(25, incoming=(SimpleNamespace(nbytes=100),))
    assert c.evicted == [1]
    assert set(c._batches) == {0,2}


def test_entry_cap_is_independent_of_byte_budget():
    c = Cache()
    c.cache_limit_entries = 2
    for i in range(2):
        c._batches[i] = (SimpleNamespace(nbytes=1),)
        c._cache_touch('flat',i)
    c._cache_room(1)
    assert c.evicted == [0]
