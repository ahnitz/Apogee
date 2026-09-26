"""Input residency shared by the Vulkan and Metal dispatch caches."""


class InputUploads:
    def _input_uploads(self, key, data, tmpl, upload_data, upload_tmpl):
        """Invalidate all resident copies when an input changes.

        Each cached storage shape owns its buffers. Clearing a caller's dirty flag
        after one dispatch cannot make the other copies current. Source slices
        also matter: equal shapes need not refer to the same data.

        The backend records the returned signature only after a successful
        write. This bookkeeping never scans or hashes the spectrum contents.
        """
        needed, signatures = [], []
        for name, array, dirty in (("data", data, upload_data),
                                   ("tmpl", tmpl, upload_tmpl)):
            resident = self._uploaded[name]
            if dirty:
                resident.clear()
            signature = (array.ctypes.data, array.shape, array.strides)
            needed.append(resident.get(key) != signature)
            signatures.append(signature)
        return (*needed, *signatures)

    cache_limit_bytes = 512 * 1024 * 1024
    cache_limit_entries = 32

    @staticmethod
    def _allocation(buf):
        owner = getattr(buf, 'owner', None)
        return owner.buffer if owner is not None else buf

    def _cached_buffers(self):
        storage = getattr(self, '_storage', None)
        if storage is not None:
            for buffers in storage.values():
                yield from (buffers.values() if isinstance(buffers, dict) else buffers)
        else:
            for batch in self._batches.values():
                yield from batch
            for batch in self._hier.values():
                yield from batch.values()
        for batch in getattr(self, '_forwards', {}).values():
            yield from batch[:-1]

    def _cache_bytes(self, incoming=()):
        allocations = {}
        for buf in (*self._cached_buffers(), *incoming):
            allocation = self._allocation(buf)
            allocations[id(allocation)] = getattr(allocation, 'nbytes', 0)
        return sum(allocations.values())

    def _cache_touch(self, kind, key):
        order = getattr(self, '_cache_order', None)
        if order is None:
            order = self._cache_order = {}
        token = (kind, key)
        order.pop(token, None)
        order[token] = None

    def _cache_room(self, estimate, *, incoming=(), keep_storage=None):
        """Evict least-recently used records, counting shared allocations once.

        Vulkan separates storage shapes from command recordings. A single
        oversized operation is still permitted; budgets bound retained work.
        Incoming shared buffers stay counted even if their last old recording
        is evicted while making room.
        """
        order = getattr(self, '_cache_order', {})
        record_limit = getattr(self, 'cache_limit_recordings', self.cache_limit_entries)
        while order:
            storage = getattr(self, '_storage', None)
            new_storage = storage is not None and keep_storage is not None and keep_storage not in storage
            too_many_shapes = new_storage and len(storage) >= self.cache_limit_entries
            if (len(order) < record_limit and not too_many_shapes
                    and self._cache_bytes(incoming) + estimate <= self.cache_limit_bytes):
                break
            kind, key = next(iter(order))
            order.pop((kind, key))
            self._evict_record(kind, key, keep_storage)
