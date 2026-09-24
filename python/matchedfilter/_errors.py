"""Errors shared by both GPU backends.

UnsupportedSize is separated from the backend error types on purpose. A
device that cannot run a transform length is a fact about the hardware, not
a fault: the Apple Paravirtual device allows this kernel 576 threads per
threadgroup and n=16384 needs 1024, so that length is simply out of reach
there. Tests must be able to tell that apart from a kernel that failed to
compile, and catching the backend's general error would hide exactly the
failures worth seeing.
"""


class UnsupportedSize(RuntimeError):
    """This device cannot run this transform length. Use a shorter one."""
