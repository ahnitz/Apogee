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
