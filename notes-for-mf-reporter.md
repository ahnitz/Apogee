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
