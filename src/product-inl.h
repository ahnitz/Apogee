/* Intentionally included twice inside the target namespace. Both load paths
   share the same dispatch and transform structure without templating the
   established staged codelets (which changes compiler code generation).
   AP_PROD_FN selects function names; AP_PROD_DATA_WIDTH selects data stride. */
static inline int AP_PROD_FN(codelet_prod)(int m,const float*restrict dr,const float*restrict di,
                               const float*restrict tr,const float*restrict ti,
                               vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,
                               long S,long DS){
  if(ap_srprod()) switch(m){
    /* 8 has no split-radix form and needs no scratch either: one radix-8 pass
       writes straight to ar. */
    case  8: return AP_PROD_FN(fft8_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    /* 16 wins at every width. */
    case 16: return AP_PROD_FN(fftsr16_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    default:
      /* 32 and 64 only at 16 lanes -- the same register-file argument that
         gates fftsr64 in codelet(), and the product form is worse off than
         the plain one because it holds four more vectors per input while it
         loads.  Measured, paired and interleaved, split-radix against
         Stockham on the pair-batched path:
         m=32 lands at n=1024, AVX-512 1.075x (6 of 6), AVX2 0.991x (2 of 4,
         and the new side swings 292-332 us against a steady 305-308), SSE4
         0.995x (0 of 4).  So it pays where the DAG fits and is a coin flip
         where it spills. */
      if constexpr (AP_W >= 16){
        if(m==32) return AP_PROD_FN(fftsr32_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
        return AP_PROD_FN(fftsr64_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
      } else {
        if(m==32) return AP_PROD_FN(fft32_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
        return AP_PROD_FN(fft64_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
      }
  }
  switch(m){
    case  8: return AP_PROD_FN(fft8_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    case 16: return AP_PROD_FN(fft16_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    case 32: return AP_PROD_FN(fft32_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    default: return AP_PROD_FN(fft64_prod)(dr,di,tr,ti,ar,ai,br,bi,S,DS);
  }
}

/* Element transform whose first pass forms conj(d*t) as it loads, so the matched
   filter's product never reaches memory and the staging buffer disappears.
   Templates are group-major, with AP_W floats per element. Data uses
   AP_PROD_DATA_WIDTH floats per element (one for scalar broadcasts). */
static void AP_PROD_FN(efft_prod)(int M,const float*restrict dr,const float*restrict di,
                      const float*restrict tr,const float*restrict ti,
                      vf*restrict X,vf*restrict Xi,vf*restrict S,vf*restrict Si,
                      const float*restrict itwr,const float*restrict itwi){
  int M1,M2; efactor(M,&M1,&M2);
  if(M2==1){ AP_PROD_FN(codelet_prod)(M,dr,di,tr,ti,X,Xi,S,Si,1,AP_W); return; }
  const int st=ESTRIDE(M1);
  /* element (e2,e1) of the group is at (e2*M1 + e1)*AP_W, so at fixed e1 the
     inner codelet walks e2 with stride M1*AP_W */
  for(int e1=0;e1<M1;e1++)
    AP_PROD_FN(codelet_prod)(M2,dr+(size_t)e1*AP_PROD_DATA_WIDTH,di+(size_t)e1*AP_PROD_DATA_WIDTH,
                 tr+(size_t)e1*AP_W,ti+(size_t)e1*AP_W,
                 X+e1,Xi+e1,S+e1,Si+e1,st,(long)M1*AP_W);
  for(int k2p=0;k2p<M2;k2p++)
    codelet_tw(M1,X+st*k2p,Xi+st*k2p,S+st*k2p,Si+st*k2p,1,
               itwr+(size_t)k2p*M1, itwi+(size_t)k2p*M1);
}

