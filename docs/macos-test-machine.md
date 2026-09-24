# Testing Metal on real Apple hardware

The macOS CI runner is an *Apple Paravirtual device*. It proves the Metal
path compiles, dispatches and agrees with the CPU. It does not characterise
the backend, and the gap is not academic:

| | paravirtual (CI) | Apple M2 |
|---|---|---|
| families | Apple1–**5**, Mac2, Common1/3 | Apple1–**8**, Mac2, Common1/3, **Metal3** |
| threadgroup memory | 32 KB | 32 KB |
| `tierb_8192_lds32` allows | **512** threads | **448** threads |
| `tierb_16384_lds32` allows | 576 | 576 |

n=8192 needs 512, so it runs in CI and raises `UnsupportedSize` on a real
M2. Testing only in CI would have shipped that as supported.

Note which way round it is: the CI device advertises a *lower* feature set
-- Apple5 is roughly an A13, below even an M1's Apple7 -- and allows *more*
threads for the same kernel. That is the shape of a different compiler
target allocating registers differently, not of more capable hardware. With
one real device there is no separating the virtualised driver from the chip
generation, and the operational point does not need it: **a CI limit
predicts a real device's limit in neither direction.**

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
