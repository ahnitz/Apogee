# peakfft - single-threaded AVX-512 FFT specialised for loudest-bin search.
CC      ?= gcc
CFLAGS  ?= -O3 -march=native -Wall -Wextra -Wno-unused-parameter
CPPFLAGS = -Iinclude -Isrc
LDLIBS   = -lm

SRC  = src/kernel1024.c src/fft1m.c src/plan.c
OBJ  = $(SRC:.c=.o)
LIB  = libpeakfft.a

# Optional references for the benchmark / cross-check.  Point these at your install.
MKLINC ?=
MKLLIB ?=
FFTWLIB ?= -l:libfftw3f.so.3

.PHONY: all test bench clean codelets
all: $(LIB) tests/test_units tests/test_topk

$(LIB): $(OBJ)
	ar rcs $@ $^

%.o: %.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -c $< -o $@

src/codelets.h: src/gen.py
	cd src && python3 gen.py
codelets: src/codelets.h

tests/test_units: tests/test_units.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)
tests/test_topk: tests/test_topk.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< $(LIB) -o $@ $(LDLIBS)

test: tests/test_units tests/test_topk
	./tests/test_units && ./tests/test_topk

# Benchmark against MKL and FFTW.  Requires MKLINC/MKLLIB to be set:
#   make bench MKLINC=/path/to/include MKLLIB=/path/to/lib
bench/bench: bench/bench.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -I$(MKLINC) $< $(LIB) -o $@ \
	  -L$(MKLLIB) -lmkl_intel_lp64 -lmkl_sequential -lmkl_core $(FFTWLIB) \
	  -Wl,-rpath,$(MKLLIB) $(LDLIBS)
bench: bench/bench
	./bench/bench

clean:
	rm -f $(OBJ) $(LIB) tests/test_units tests/test_topk bench/bench

tests/test_vs_mkl: tests/test_vs_mkl.c $(LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -I$(MKLINC) $< $(LIB) -o $@ \
	  -L$(MKLLIB) -lmkl_intel_lp64 -lmkl_sequential -lmkl_core -Wl,-rpath,$(MKLLIB) $(LDLIBS)
test-mkl: tests/test_vs_mkl
	./tests/test_vs_mkl
