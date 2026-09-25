# How to optimise a kernel here

Written after a long session on the GPU coarse stage in which five
plausible hypotheses were falsified by measurement, one "2.27x speedup"
turned out to be a correctness bug, and the changes that finally worked
were the ones that deleted work rather than speeding it up. These are the
rules that survived. They apply to the other kernel variants, to the CPU
path, and to whatever comes next.

## 1. Account before you optimise

Derive what the algorithm **requires** -- the irreducible operation count
-- from the maths, not from the code. Then count what the code actually
executes. The gap is the entire opportunity, and its composition tells you
what to attack.

For the coarse stage this produced: 501 irreducible VALU per thread per
pair at band 512 against 1029 executed, i.e. **51% of instructions were
addressing, not arithmetic**. No amount of staring at the code would have
produced that number, and every hypothesis formed before it was wrong.

Sanity-check the model against a measurement: instructions x pairs / issue
rate should land near the measured time. If it does not, the model is
wrong and so is everything built on it.

## 2. Track what the hardware is NOT using

Optimisation is finding idle capacity and spending it. Keep a table, per
configuration, of: idle lanes, waves resident vs capacity, VGPRs used,
LDS used, L1/L2 pressure.

The coarse stage ran at **50% occupancy at every band** -- but the binding
constraint differed (workgroup cap at small bands, LDS at large, both at
once at band 512). That single table explained a dozen earlier null
results.

## 3. Find which constraint binds, per configuration

A resource that is not binding is not a lever. Relieving a non-binding
constraint measures as **exactly zero**, which reads as "this idea does not
work" when the truth is "this idea is blocked by something else".

Worked example: at band 512, LDS and the 16-workgroup cap bound
simultaneously at 16 groups. Halving LDS alone -> still 16 groups (cap).
Two pairs per group alone -> LDS doubles, 8 groups of 2 waves = 16 again.
Both measured neutral **in isolation and only together do they reach full
occupancy**. If two changes each measure neutral, ask whether each is
blocked by the other before discarding them.

## 4. Prefer deleting work to making work cheaper

Ranked by what actually worked here:

  1. **Delete it.** Specialising the coarse gate to one bin -- it reports
     one value per pair by construction -- was the first change to improve
     the large bands at all (+13-14%), after six attempts at making the
     same instructions cheaper returned nothing.
  2. **Amortise it.** Work that depends only on thread and level, not on
     the data, can be hoisted across a tile or precomputed on upload.
  3. **Make it cheaper.** Last resort. fp16 loads, fp16 math, half2 LDS,
     permuted layouts and wide loads each returned ~0 at the large bands.

Ask of every term: does the OUTPUT CONTRACT actually require this? The
coarse stage computed a digit-reversed index it never reported, because it
shared code with a stage that does.

## 5. Exploit the problem's structure, and pay preparation once

An N x M batch means every data row is read by M pairs and every template
by N. That redundancy is free to exploit. Anything that can be rearranged
**once on upload** and reused across the grid costs nothing at grid scale
-- so layout is a free variable, chosen for the kernel's convenience.

Check that preparation really is outside the timed loop before claiming it.

## 6. Coalescing beats instruction count

Two pre-permutations cut load instructions 4x and **lost 17%**, because
they put a wave's lanes a cache line apart. Adjacent lanes must touch
adjacent addresses. Make that an input to any layout, not something
rediscovered afterwards.

## 7. A speedup that is not verified correct is not a speedup

This is the one that cost most. Packing four pairs into a wave measured
**2.27x** -- because the wave-wide max reduction mixed the pairs and
silently dismissed three quarters of the signals. Faster and wrong look
identical on a stopwatch, and gating/prefilter code fails in exactly the
direction that makes it fast.

**Measure timing and correctness in the same breath, every time.**

## 8. Test where the feature actually lives

That bug survived a 419-test suite because it only appeared at band 128,
and every cross-device test skips that band -- there is no CPU plan for it.

When the natural reference is unavailable, find one that does not need it:
here, hierarchical against the **flat filter on the same device**, which
needs no CPU plan and no table. Then verify the test is not vacuous by
reintroducing the bug and watching it fail.

## 9. Distrust your own measurements

Specific traps hit in one session:

  * **Dead-code elimination.** Stubbing a function out to price it gives a
    free speedup if the compiler then deletes its consumers. Force the
    result live before believing the number.
  * **Host work inside the timed loop.** Check whether uploads/packing
    re-run per iteration.
  * **Run-to-run variance.** +-15% at band 128, +-7% at 512 here. Single
    runs argued the opposite conclusion twice. Report means of >=3, and
    call anything inside the spread "neutral" rather than a win or a loss.
  * **Statistical power.** A budget test with 120 clumped trials cannot
    measure a 1% rate; the pass/fail line sat between 3 and 4 events.
  * **Plausible-but-wrong.** A broken FFT decomposition landed within a few
    percent of the right peak magnitude and read as a precision effect.
    Verify a transform reproduces the exact reference at full precision
    before drawing any conclusion about precision.

## 10. Verify the mechanism, not just the outcome

Two builds had identical byte size, which looked like "fp16 was widened to
fp32". Checking the SPIR-V capability list showed Float16 was genuinely
emitted and the size match was coincidence. When a result surprises you,
confirm the mechanism is what you think before concluding anything.

## 11. Read the compiled code before the fifth guess

Source-level reasoning mispredicted five consecutive changes on the coarse
stage. Two reads of the compiled output produced durable facts immediately:

  * `RADV_DEBUG=shaderstats` -- VGPR/SGPR, spills, scratch, LDS, waves per
    SIMD. Showed the kernel at 216 VGPRs where the model said ~112, which
    meant REGISTER PRESSURE was binding rather than the workgroup cap, and
    retro-explained every failed tile experiment. Also found a dead kernel
    compiled for every plan and never dispatched -- 256 VGPRs, 18 spilled.
  * `RADV_DEBUG=asm` + `MESA_SHADER_CACHE_DISABLE=1` -- the instruction mix.
    Showed 789 SCALAR half ops against 928 packed: nearly half the fp16
    arithmetic was running at half rate because a complex multiply is a
    CROSS pattern that cannot lower to elementwise v_pk_*. That is why
    "fp16 math" had measured 4% -- half of it was never fp16 math.

Both reads took minutes and each invalidated a model that had survived
several experiments. **When a model has mispredicted twice, stop testing
predictions and go read what the hardware was given.** Note the shader
cache will hide the dump on a re-run of an unchanged shader.

Corollary: a type change can be storage-only. `typedef half2 C` halved the
STORAGE and left the ARITHMETIC unpacked, and nothing at source level said
so. Packing requires the data layout to match the instruction -- for
complex, that means split/SoA (re0,re1),(im0,im1) rather than (re,im).

## 12. Vectorisation is a LAYOUT property, not a type property

`typedef half2 C` halved the storage and left the arithmetic unpacked: 789
scalar half ops against 928 packed. Nothing at source level said so. A
packed instruction needs its operands laid out the way the instruction
consumes them -- elementwise, lane by lane -- and a complex multiply
(ax*bx - ay*by, ax*by + ay*bx) is a CROSS pattern that never satisfies that
in interleaved (re,im) form.

The same trap is waiting on every SIMD target. AoS complex under AVX or
NEON degrades into shuffles and scalar-width work in exactly this way; the
CPU path here already uses split complex for precisely this reason. When
adopting a narrower type for speed, verify in the disassembly that the
arithmetic packed -- the declaration will not tell you.

**And when you do go SoA, check WHICH axis to pair along.** The obvious
choice is usually wrong. Pairing adjacent elements within one transform
puts a radix-4 butterfly's operands (o, o+4, o+8, o+12) at the same
component of four different registers, so every butterfly needs a component
extract -- reintroducing the exact moves being eliminated. Pair across two
INDEPENDENT problems instead: two transforms, two pairs, two rows. Then the
lanes never interact, every operation is elementwise, and the register cost
is identical to holding the two problems separately.

Corollary: **a partial conversion is worse than either endpoint.** The
boundary between AoS and SoA regions costs precisely the gather/scatter
being removed, so this class of change has to land in one go or not at all.

## 13. Commit hygiene while optimising

`git add -A` swept an unrelated in-progress refactor into a commit and put
a 40% regression on main for two commits. When experimenting, commit
explicit paths, and re-measure after reverting an experiment to confirm you
are back where you think you are.
