"""Choosing where a filter runs.

The spelling is PyTorch's -- ``"cpu"``, ``"gpu"``, ``"gpu:1"`` -- because that
is what a user already has in their fingers, and a library that invents a
fourth convention for a solved problem is only making work.

Two decisions are deliberate and easy to get wrong later:

*Default is the CPU, never the GPU.*  Running somewhere else because that
somewhere happens to exist changes numerics and failure modes without the
caller asking for it.  ``device="auto"`` is available for people who want the
library to choose, but they have to say so.

*A software rasteriser is not a GPU.*  lavapipe answers ``device="gpu"``
correctly and roughly a thousand times slower than the CPU backend the caller
just bypassed, which reads as a performance bug and is really a selection bug.
It is reachable, but only by naming it.
"""
import os

from . import _metal
from . import _vulkan

_VENDORS = {0x1002: "AMD", 0x10DE: "NVIDIA", 0x8086: "Intel",
            0x13B5: "ARM", 0x5143: "Qualcomm", 0x106B: "Apple"}


def arch_keys(vendor, name):
    """Cost-table names to try for a device, most specific first.

    Cost is a property of the machine, so a table measured on one device is
    only loosely transferable. The chain lets a table be shared by as much
    hardware as it honestly covers:

        gfx1151   this exact architecture
        gfx11     its family -- RDNA 3 and 3.5 share the memory hierarchy and
                  the workgroup limits that the measurements actually depend on
        amd       the vendor
        (generic) the shipped table, measured on a CPU

    The architecture comes out of the device name because Vulkan does not
    report it: Mesa writes it there as "RADV GFX1151", and the vendor id
    distinguishes AMD from anyone else naming a device similarly.
    """
    import re
    keys = []
    vendors = {0x1002: "amd", 0x10DE: "nvidia", 0x8086: "intel", 0x106B: "apple"}
    v = vendors.get(vendor)
    m = re.search(r"gfx(\d{3,4})", name or "", re.I)
    if m:
        full = "gfx" + m.group(1)
        keys.append(full)
        keys.append("gfx" + m.group(1)[:2])      # the family
    if v:
        keys.append(v)
    return keys


class Device:
    """One place a filter can run.  Compare and print it as ``"gpu:0"``."""

    __slots__ = ("kind", "index", "name", "backend", "is_software", "arch")

    def __init__(self, kind, index, name, backend, is_software=False, arch=()):
        self.kind = kind
        self.index = int(index)
        self.name = name
        self.backend = backend
        self.is_software = bool(is_software)
        #: Cost-table keys to try, most specific first.  Empty for a CPU.
        self.arch = tuple(arch)

    def __str__(self):
        return "%s:%d" % (self.kind, self.index)

    def __repr__(self):
        tail = ", software=True" if self.is_software else ""
        return "Device('%s', %r, backend=%r%s)" % (self, self.name,
                                                   self.backend, tail)

    def __eq__(self, other):
        if isinstance(other, str):
            # Comparison must be total: asking whether this is "gpu:0" on a
            # machine with no GPU is a fair question with the answer "no",
            # not an error. parse() raises for absent or malformed devices,
            # which is right when selecting and wrong when comparing.
            try:
                other = parse(other)
            except (ValueError, RuntimeError, TypeError):
                return False
        return (isinstance(other, Device) and self.kind == other.kind
                and self.index == other.index)

    def __hash__(self):
        return hash((self.kind, self.index))


def _cpu_device():
    from . import backend as _backend
    import platform
    try:
        name = None
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    name = line.split(":", 1)[1].strip()
                    break
    except OSError:
        name = None
    return Device("cpu", 0, name or platform.processor() or "CPU",
                  _backend())


def devices():
    """Every device this build can dispatch to, CPUs first.

    Software Vulkan devices are listed -- hiding them would make the CI path
    undiscoverable -- but flagged, and ``"gpu"`` without an index skips them.
    """
    out = [_cpu_device()]

    # Metal first, because on macOS it is the only way an Apple GPU can be
    # seen at all -- there is no Vulkan driver there. Listing it does not
    # claim it can be used: backend="metal" has no runtime yet and building
    # a filter on it refuses, which is a better answer than reporting that
    # a machine with a GPU has none.
    for i, d in enumerate(_metal.enumerate_devices()[0]):
        out.append(Device("gpu", i, d["name"], "metal",
                          arch=("apple",)))

    found, _ = _vulkan.enumerate_devices()
    base = len(out) - 1
    for i, d in enumerate(found):
        i += base
        vendor = _VENDORS.get(d["vendor"])
        name = d["name"]
        if vendor and vendor.lower() not in name.lower():
            name = "%s %s" % (vendor, name)
        out.append(Device("gpu", i, name, "vulkan",
                          is_software=d["kind"] == "cpu",
                          arch=arch_keys(d["vendor"], d["name"])))
    return out


def parse(spec):
    """Turn ``None`` / a string / a :class:`Device` into a :class:`Device`.

    ``None`` consults ``MF_DEVICE`` and otherwise gives the CPU, so a harness
    can move a whole benchmark to another backend without editing the code
    that builds the plans -- the same reason ``MF_ISA`` exists.
    """
    if isinstance(spec, Device):
        return spec
    if spec is None:
        spec = os.environ.get("MF_DEVICE") or "cpu"
    if not isinstance(spec, str):
        raise TypeError("device must be a string or Device, got %r" % (spec,))

    text = spec.strip().lower()
    if text == "auto":
        ok, _ = _vulkan.available()
        text = "gpu" if ok else "cpu"

    kind, _, ordinal = text.partition(":")
    if kind not in ("cpu", "gpu"):
        raise ValueError(
            "unknown device %r -- expected 'cpu', 'gpu', 'gpu:<n>' or 'auto'"
            % spec)
    if ordinal and not ordinal.isdigit():
        raise ValueError("device ordinal must be an integer, got %r" % spec)

    all_devices = devices()
    candidates = [d for d in all_devices if d.kind == kind]
    if ordinal:
        wanted = int(ordinal)
        for d in candidates:
            if d.index == wanted:
                return d
        raise ValueError("no %s with index %d; available: %s"
                         % (kind, wanted,
                            ", ".join(str(d) for d in all_devices)))

    if kind == "cpu":
        return candidates[0]

    # Bare "gpu": real hardware only, for the reason in the module docstring.
    for d in candidates:
        if not d.is_software:
            return d
    ok, reason = _vulkan.available()
    raise RuntimeError(
        "no GPU available: %s. Pass device='gpu:<n>' to select a specific "
        "device (including a software one), or device='cpu'."
        % (reason or "unknown"))
