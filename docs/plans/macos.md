# macOS on the GPU

> **Status: not implemented.** The wheel installs and the CPU path works on a
> Mac; `device="gpu"` refuses because no Vulkan loader is found. This is what
> it would take, with the parts that are already done marked.

## Why it does not work today

The backend is Vulkan. The wheel carries SPIR-V and the runtime `dlopen`s
whatever Vulkan loader the system provides. macOS ships none, and we bundle
none, so `_vulkan._load()` finds no `libvulkan.1.dylib` and every GPU call
refuses with a clear message.

Nothing else is missing. The two things that usually block a Metal port are
already handled, and both were done for other reasons:

| | status |
|---|---|
| SPIR-V uses only portable features | done — `Shader`, `Groups`, `SubgroupBallotKHR`, nothing else |
| Apple's 32 KB threadgroup memory limit | done — every kernel over it also ships a 32 KB build, picked at run time |
| Apple's 1024-invocation workgroup limit | done — queried, and a device offering fewer is refused by name |
| the kernel compiles to Metal at all | done — `slangc -target metal` emits MSL today |

The generated MSL uses `simd_max`, `simd_is_first`, `atomic_fetch_max_explicit`
and `threadgroup` arrays. All are ordinary Metal; none are the sort of thing
that turns into a rewrite.

## Route A: bundle MoltenVK

MoltenVK implements Vulkan on Metal, is Apache 2.0, and exports the Vulkan
entry points directly — so `libMoltenVK.dylib` can be `dlopen`ed in place of
a loader and the existing SPIR-V runs unchanged.

1. Add `libMoltenVK.dylib` to the macOS wheels. cibuildwheel's repair step
   is where it goes, and the licence has to travel with it.
2. Teach `_vulkan._load()` to try the bundled copy first, then
   `libMoltenVK.dylib`, then `libvulkan.1.dylib` for anyone who has a real
   loader and a translation layer already set up.
3. Measure a cost table for Apple and ship it as `cost-apple.txt`. The
   `gfx11` table does not apply, and falling back to the CPU's would choose
   badly rather than incorrectly.
4. Re-measure the staging table. `tools/build_spirv.py` holds one measured
   on a Radeon; the tradeoff it encodes -- barriers against occupancy -- has
   no reason to land in the same place on Apple hardware.

**What could still go wrong**, and none of it is visible from here: MoltenVK
converts SPIR-V to MSL at pipeline creation, so plan building is slower than
on a native driver; subgroup coverage on older Apple GPUs is worth checking
rather than assuming; and `n=16384` wants the full 1024-thread workgroup,
which is the limit rather than comfortably inside it.

Effort: packaging plus a loader path. The kernels do not change.

## Route B: emit Metal directly

`slangc -target metal` already produces MSL from the same source. Two pieces
are missing:

1. **The final compile.** `-target metallib` needs Apple's `metal` compiler,
   which exists only on macOS, so the blob has to be built on a Mac runner
   rather than wherever the rest of the wheels are built.
2. **A Metal runtime.** `_vkcompute.py` is ctypes over Vulkan; Metal would
   need its own, through `objc_msgSend` against `Metal.framework` or a small
   compiled extension. Buffers, a command queue, a compute pipeline state and
   a dispatch — the same shape as the Vulkan one, perhaps 400 lines.

Effort: larger, but no translation layer between the kernel and the device,
and pipeline creation would be a blob load rather than a shader compile.

## Which first

Route A, because it reuses everything and the kernels are already known to be
portable. Route B becomes worth it if MoltenVK's pipeline-creation cost or
its subgroup coverage turns out to bite -- and by then the cost tables and
the CI job from Route A still apply.

**Neither can be developed blind.** There is no Apple hardware here, so the
first step either way is a CI job that runs the existing suite on a macOS
runner with MoltenVK installed, to find out what actually fails before
choosing how much to build.
