# peakfft - single-threaded AVX-512 FFT specialised for loudest-bin search.
CC      ?= gcc
CFLAGS  ?= -O3 -Wall -Wextra -Wno-unused-parameter
CPPFLAGS = -Iinclude -Isrc
LDLIBS   = -lm

# AVX-512 sources, AVX2 sources and the ISA-neutral dispatcher are compiled with
# different -m flags, so the library is safe to load on a machine without AVX-512.
AVX512FLAGS = -DPF_W=16 -mavx512f -mavx512dq -mavx512bw -mavx512vl
AVX2FLAGS   = -mavx2 -mfma
BASEFLAGS   =

OBJ512 = src/kernel1024.o src/be_avx512.o
OBJGEN = src/balanced16.o src/balanced8.o
OBJB   = src/dispatch.o
OBJ    = $(OBJ512) $(OBJGEN) $(OBJB)
LIB    = libpeakfft.a

# Optional references for the benchmark / cross-check.  Point these at your install.
MKLINC ?=
MKLLIB ?=
FFTWLIB ?= -l:libfftw3f.so.3

.PHONY: all test quick bench clean codelets ab
all: $(LIB) tests/test_units tests/test_topk tests/test_batch tests/test_binmax

$(LIB): $(OBJ)
	ar rcs $@ $^

# Shared build, so bench/ab can hold two versions of the library at once.
# -fPIC is applied to a separate object set to keep the static build unchanged.
SO = libpeakfft.so
$(SO): $(OBJ:.o=.pico)
	$(CC) -shared -o $@ $^
%.pico: %.c
	$(CC) $(CFLAGS) $(AVX512FLAGS) $(CPPFLAGS) -fPIC -c $< -o $@
src/balanced16.pico: src/balanced.c
	$(CC) $(CFLAGS) $(AVX512FLAGS) $(CPPFLAGS) -fPIC -c $< -o $@
src/balanced8.pico: src/balanced.c
	$(CC) $(CFLAGS) $(AVX2FLAGS) $(CPPFLAGS) -fPIC -DPF_W=8 -c $< -o $@
src/dispatch.pico: src/dispatch.c
	$(CC) $(CFLAGS) $(BASEFLAGS) $(CPPFLAGS) -fPIC -c $< -o $@

# Paired A/B of two library builds, interleaved so machine drift cancels.
#   make ab BASE=/tmp/base.so
bench/ab: bench/ab.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $< -o $@ -ldl -lm
ab: bench/ab $(SO)
	@test -n "$(BASE)" || { echo "set BASE=<baseline .so>; e.g. make $(SO) && cp $(SO) /tmp/base.so"; exit 1; }
	./bench/ab $(BASE) ./$(SO) $(ABFLAGS)

$(OBJ512): %.o: %.c
	$(CC) $(CFLAGS) $(AVX512FLAGS) $(CPPFLAGS) -c $< -o $@
src/balanced16.o: src/balanced.c
	$(CC) $(CFLAGS) $(AVX512FLAGS) $(CPPFLAGS) -c $< -o $@
src/balanced8.o: src/balanced.c
	$(CC) $(CFLAGS) $(AVX2FLAGS) $(CPPFLAGS) -DPF_W=8 -c $< -o $@
$(OBJB): %.o: %.c
	$(CC) $(CFLAGS) $(BASEFLAGS) $(CPPFLAGS) -c $< -o $@

src/codelets.h: src/gen.py
	cd src && python3 gen.py
codelets: src/codelets.h

tests/test_units: tests/test_units.c $(LIB)
	$(CC) $(CFLAGS) $(AVX512FLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)
tests/test_topk: tests/test_topk.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)
tests/test_batch: tests/test_batch.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)
tests/test_binmax: tests/test_binmax.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)

# Correctness gate small enough to run between edits.  Not a substitute for
# 'make test' - it is what you run 20 times an hour, not once.
quick: tests/test_units tests/test_batch tests/test_binmax
	./tests/test_units
	PF_QUICK=1 ./tests/test_batch
	PF_QUICK=1 ./tests/test_binmax

test: tests/test_units tests/test_topk tests/test_batch tests/test_binmax
	./tests/test_units && ./tests/test_topk && ./tests/test_batch && ./tests/test_binmax
	@echo "--- forcing the AVX2 back end ---"
	PEAKFFT_ISA=avx2 ./tests/test_topk && PEAKFFT_ISA=avx2 ./tests/test_batch && PEAKFFT_ISA=avx2 ./tests/test_binmax
	@echo "--- forcing the generic back end at 16 lanes ---"
	PEAKFFT_ISA=balanced512 ./tests/test_topk && PEAKFFT_ISA=balanced512 ./tests/test_batch && PEAKFFT_ISA=balanced512 ./tests/test_binmax

# Benchmark against MKL and FFTW.  Requires MKLINC/MKLLIB to be set:
#   make bench MKLINC=/path/to/include MKLLIB=/path/to/lib
bench/bench: bench/bench.c $(LIB)
	$(CC) $(CFLAGS) $(AVX2FLAGS) $(CPPFLAGS) -I$(MKLINC) $< $(LIB) -o $@ \
	  -L$(MKLLIB) -lmkl_intel_lp64 -lmkl_sequential -lmkl_core $(FFTWLIB) \
	  -Wl,-rpath,$(MKLLIB) $(LDLIBS)
bench: bench/bench
	./bench/bench

clean:
	rm -f $(OBJ) src/*.o src/*.pico $(LIB) $(SO) bench/ab tests/test_units tests/test_topk tests/test_batch tests/test_binmax bench/bench

tests/test_vs_mkl: tests/test_vs_mkl.c $(LIB)
	$(CC) $(CFLAGS) $(AVX2FLAGS) $(CPPFLAGS) -I$(MKLINC) $< $(LIB) -o $@ \
	  -L$(MKLLIB) -lmkl_intel_lp64 -lmkl_sequential -lmkl_core -Wl,-rpath,$(MKLLIB) $(LDLIBS)
test-mkl: tests/test_vs_mkl
	./tests/test_vs_mkl

# Four-way comparison: MKL, stock FFTW (dlopen+DEEPBIND), amd-fftw, peakfft.
# AMDFFTW must point at an AOCL-FFTW install; its archive is linked whole and
# ahead of MKL, otherwise MKL's own fftwf_* wrappers win and both FFTW columns
# silently become MKL again.
AMDFFTW ?=
bench/bench4 bench/bench_batch: bench/%: bench/%.c $(LIB)
	$(CC) $(CFLAGS) $(AVX2FLAGS) $(CPPFLAGS) -Ibench -I$(MKLINC) $< $(LIB) -o $@ \
	  -Wl,--whole-archive $(AMDFFTW)/lib/libfftw3f.a -Wl,--no-whole-archive \
	  -L$(MKLLIB) -lmkl_intel_lp64 -lmkl_sequential -lmkl_core -Wl,-rpath,$(MKLLIB) \
	  -ldl -lm -rdynamic
