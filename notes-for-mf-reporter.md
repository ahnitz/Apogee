# Re: the two correctness bugs — neither reproduces through the library API

I ran **exactly the check your report recommends** for Bug 2: flat CPU
`run_series` against flat GPU `run_series`, same inputs, same call, assert
the index arrays equal. Result, n=4096, 142 blocks x 64 templates,
**6139 triggers**:

    flat  cpu-vs-gpu:  0 index mismatches of 6139 overlapping,
                       0 cpu-only, 0 gpu-only, |value| max diff 3.8e-06
    hier  cpu-vs-gpu:  0 index mismatches of 6139 overlapping

And for Bug 1, the one-sided guarantee on the same run:

    cpu:  flat 6139, hier 6139, dismissed 0, PROMOTED 0
    gpu:  flat 6139, hier 6139, dismissed 0, PROMOTED 0

Single-block `run()` agrees too: 0 mismatches across 553 peaks at three
(n, nd, nt) shapes.

**So the "~26% of the set at the wrong index" does not appear anywhere I
can produce it**, and neither does a promoted trigger.

## Your own follow-up is very likely the answer

You raised it yourself: with `--cluster-window 1`, only the loudest
trigger in the window survives. If hier legitimately dismisses the loudest
in a cluster, the **second loudest is promoted into the output** at a
different time. That reads as "a trigger stock never reported" in a set
diff, while being a downstream consequence of a legitimate dismissal
rather than the gate inventing anything. It also explains the shape of
Bug 2: a count that is nearly right with a large fraction of the SET
different is what re-clustering does, not what an index-mapping bug does
(that would move peaks within a block and would show up in the raw
comparison above, which is clean).

## What I did NOT rule out

  * your exact configuration — I used 142 blocks and 64 templates against
    your ~245 and 64, and my own coloured series, not your data;
  * anything downstream of `run_series(raw=True)` — clustering, coincidence,
    ranking. My comparison stops at the raw index/value arrays;
  * a load-dependent effect. You noted the machine hit load 36 mid-run; my
    numbers are counters, so if yours were too this does not apply, but if
    any part of the harness was timing-sensitive it is worth re-running
    quiet.

## What would settle it on your side

Take the raw arrays BEFORE clustering — `run_series(raw=True)` for stock
and for hier — and diff those sets. If they agree there and disagree after
clustering, it is the cluster window and there is no library bug. That is
a two-line change to your harness and it is decisive.

## Pinned in the suite now

`test_cpu_and_gpu_agree_through_run_series` asserts index equality across
devices for both flat and hierarchical, plus PROMOTED == 0 per device, so
this cannot drift. It also asserts it found >500 triggers first -- an
unscaled coloured series yields ZERO at any useful threshold, and the test
would otherwise pass by comparing two empty sets. That vacuity trap is
real: my first two attempts at this comparison found 0 triggers and looked
like clean passes.

---

# Update: your SNR-value finding is right, and my rebuttal was too narrow

You are correct that clustering cannot change the value of a trigger both
engines found at the same sample, and my check could not have seen it: I
asserted INDEX equality and merely printed the value difference without
asserting on it. That is now fixed.

## What reproduces here

Scanning five configurations, comparing |SNR| at matching
(block, template, index):

    n     nt  taps  blocks  common  max rel    >1e-6 rel  gpu-LOWER
    4096  32  451   70      1307    1.37e-06   103        1264
    4096  64  451   70      2622    1.37e-06   211        2527
    4096  64  1025  84      2986    1.37e-06   101        2875
    2048  32  451   162     1702    1.23e-06    25        1647
    8192  32  451   32       840    1.51e-06   159         833

**The DIRECTION reproduces exactly**: the GPU is systematically lower,
~97% of differing points, matching your 552-of-573. So this is a real,
consistent difference in how the value is computed -- not a race, not
clustering.

**The MAGNITUDE does not**: 1.4e-06 relative here against your 13%.

## What I think that means

Same mechanism, different conditioning. A systematic one-sided bias of
this size is accumulation ORDER -- the GPU sums the correlation in a
different sequence, and float32 addition is not associative. On my
synthetic coloured noise the terms are well scaled and it stays at
roundoff. Whitened real data through a PSD has far greater dynamic range
and much more cancellation between large terms, which is exactly the
regime where a reordered sum loses relative precision catastrophically.
13% on 6.6% of peaks is consistent with that; it is not consistent with a
lag-mapping bug, which would move peaks rather than devalue them.

That also predicts something you can check cheaply: the bad points should
correlate with template CONDITIONING -- how much cancellation that
template's correlation involves -- rather than with position in the
segment or template index, both of which you found uniform.

## What would confirm it

Compute one of the 573 disagreeing triggers in float64 on the host, at
that exact (block, template, lag). If float64 lands near the CPU value,
the CPU is right and the GPU is losing precision. If it lands between
them, both are lossy and the GPU is merely worse. Either way it localises
to summation, and the fix is a compensated or higher-precision accumulate
in the GPU's final reduction rather than anything structural.

## Pinned now

`test_cpu_and_gpu_agree_through_run_series` asserts relative value
agreement below 1e-4 at matching (block, template, index), alongside the
index equality it already had. 1e-4 sits far above the 1.4e-06 roundoff
measured here and far below anything that can flip a threshold, so it
catches a divergence like yours without failing on float32 noise.
