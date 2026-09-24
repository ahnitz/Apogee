# Testing Metal on real Apple hardware

The macOS CI runner is an *Apple Paravirtual device*. It is enough to prove
the Metal path compiles, dispatches and agrees with the CPU, and it is not
enough to characterise the backend: a paravirtual GPU reports different
limits from real silicon, and the differences are the kind that decide
whether a transform length works at all.

Measured on the same kernel, same commit:

| pipeline            | paravirtual (CI) | Apple M2 |
|---------------------|------------------|----------|
| `tierb_8192_lds32`  | 512 threads      | **448**  |
| `tierb_16384_lds32` | 576 threads      | 576      |

n=8192 needs 512, so it runs in CI and **fails on a real M2**. Testing only
in CI would have shipped that.

## The machine

`empire` — Apple M2, 10 GPU cores, macOS 26, arm64. Reached over SSH; the
entry in `~/.ssh/config` proxies through `its-condor-t1.syr.edu`.

What it has: `python3` (3.9.6, system), `git`, `curl`, `rsync`, `clang`,
Command Line Tools.

What it does **not** have, and why that is useful:

- **No full Xcode**, so no `xcrun metal` and no way to build a `.metallib`.
  Every run there exercises the runtime source-compile fallback — which is
  what a user without Xcode gets from the wheel. Measured cost: 0.169 s on
  the first call at n=4096, once per pipeline.
- No `cmake`. Nothing needs it; the build is plain setuptools.

## The rule

**Everything lives in one folder and nothing is created outside it.**
Including installed software. `env.sh` enforces it by pointing every cache
a tool might use back inside the folder, `HOME` included — which is what
stops pip and python writing to `~/Library` and `~/.cache`.

```
~/matchedfilter-metal/
  env.sh        source this first; sets HOME, TMPDIR, PIP_CACHE_DIR,
                XDG_CACHE_HOME, PYTHONPYCACHEPREFIX, PATH
  repo/         the source, rsynced from the development machine
  venv/         the virtualenv
  cache/        pip and friends
  tmp/          TMPDIR
  toolchain/    anything downloaded, e.g. slangc
```

Overriding `HOME` means the remote has no access to your SSH keys, so it
cannot `git clone`. That is deliberate: the source is pushed from the
development machine with `rsync` instead, which keeps the remote a pure
build-and-test target with no credentials on it.

## The loop

From the repository root on the development machine:

```bash
# 1. push the working tree (no git credentials needed on the remote)
rsync -az --delete \
  --exclude '.git/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude 'build/' --exclude '*.egg-info/' --exclude '.pytest_cache/' \
  ./ empire:matchedfilter-metal/repo/
git rev-parse --short HEAD | ssh empire 'cat > matchedfilter-metal/repo/COMMIT'

# 2. first time only
ssh empire 'source $HOME/matchedfilter-metal/env.sh; cd $MF_PROJ
  python3 -m venv venv
  python -m pip install -q --upgrade pip setuptools wheel
  python -m pip install -q numpy pytest'

# 3. build and test
ssh empire 'source $HOME/matchedfilter-metal/env.sh; cd $MF_PROJ/repo
  python -m pip install -q . && python -m pytest tests -q -rs'
```

`-rs` matters. A Metal limitation shows up as a skip with the device's own
words in it, not as a failure, so the skip reasons are the result.

## What it has found

- `device="auto"` resolved to the CPU on a Mac. It asked
  `_vulkan.available()` and nothing else, and macOS has no Vulkan driver —
  so `auto` silently declined a working Metal GPU. Nothing on a Linux box
  can see this.
- n=8192 exceeds the M2's per-pipeline thread limit, where the CI device
  allows it.

## Cleaning up

```bash
ssh empire 'rm -rf $HOME/matchedfilter-metal'
```

One directory, because nothing was written outside it.
