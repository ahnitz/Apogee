"""Input residency shared by the Vulkan and Metal dispatch caches."""


class InputUploads:
    def _input_uploads(self, key, data, tmpl, upload_data, upload_tmpl):
        """Invalidate all resident copies when an input changes.

        Each cached dispatch owns its buffers. Clearing a caller's dirty flag
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

    def _cache_room(self, estimate):
        """Bound retained dispatch buffers; one oversized dispatch is allowed.

        Called only on cache misses. Clearing batches keeps compiled pipelines,
        and every backend submits synchronously before buffers can be evicted.
        """
        used = 0
        for batch in self._batches.values():
            used += sum(getattr(b, 'nbytes', 0) for b in batch)
        for batch in self._hier.values():
            bufs = batch[0] if isinstance(batch, tuple) else batch
            used += sum(getattr(b, 'nbytes', 0) for b in bufs.values())
        entries = len(self._batches) + len(self._hier)
        if entries and (used + estimate > self.cache_limit_bytes
                        or entries >= self.cache_limit_entries):
            self.clear_cache()
