/* Synthetic memory-system load, to reproduce the contended regime on an idle box.
   Each worker streams read-modify-write over a buffer far larger than L3, which is
   what actually destroyed L3 residency and per-core bandwidth in the original
   measurements (load avg ~35, L3 down to 2.7 GB/s). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
static volatile int run=1;
static void stop(int s){(void)s;run=0;}
int main(int argc,char**argv){
  size_t mb = argc>1?(size_t)atol(argv[1]):96;
  signal(SIGTERM,stop); signal(SIGINT,stop);
  size_t n=mb<<20; char*b=malloc(n);
  if(!b) return 1;
  memset(b,1,n);
  volatile unsigned long long acc=0;
  while(run){
    for(size_t i=0;i<n;i+=64){ b[i]++; acc+=(unsigned long long)b[i]; }
  }
  return (int)(acc&1);
}
