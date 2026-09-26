import math, sys
# Generate fully-unrolled Stockham autosort SoA vector FFT codelets.
# Data: __m512 xr[n], xi[n]  (element index = transform index; SIMD lanes = independent transforms)
def wconst(k,n):
    a=-2*math.pi*k/n
    return (math.cos(a), math.sin(a))
def trivial(c,s,tol=1e-12):
    for (v,name) in ((1,0),):
        pass
    if abs(c-1)<tol and abs(s)<tol: return "1"
    if abs(c+1)<tol and abs(s)<tol: return "-1"
    if abs(c)<tol and abs(s+1)<tol: return "-i"
    if abs(c)<tol and abs(s-1)<tol: return "+i"
    return None

class Gen:
    def __init__(s,n,name,tw=False,preload=False,prod=False):
        s.n=n; s.name=name; s.L=[]; s.consts={}; s.nc=0; s.tw=tw; s.preload=preload
        # prod: the first radix pass reads two spectra straight from memory and
        # forms conj(d*t) as it loads.  The matched filter otherwise writes that
        # product into a staging buffer that this codelet immediately reads back
        # - a whole round trip through L1 per pass, for arithmetic that is four
        # FMAs and can just as well happen here.
        s.prod=prod
    def emit(s,l): s.L.append("  "+l)
    def const(s,c,v):
        key=("%.17g"%v)
        if key not in s.consts:
            nm="c%d"%len(s.consts); s.consts[key]=nm
        return s.consts[key]
    # complex multiply (re,im) by constant twiddle (c,sn) -> new names
    def cmul(s,ar,ai,c,sn,out):
        t=trivial(c,sn)
        orr,oii=out
        if t=="1":
            s.emit("vf %s=%s, %s=%s;"%(orr,ar,oii,ai)); return
        if t=="-1":
            s.emit("vf %s=V_SUB(Z,%s), %s=V_SUB(Z,%s);"%(orr,ar,oii,ai)); return
        if t=="-i":   # (a)(-i) = ai_ - i*ar
            s.emit("vf %s=%s, %s=V_SUB(Z,%s);"%(orr,ai,oii,ar)); return
        if t=="+i":
            s.emit("vf %s=V_SUB(Z,%s), %s=%s;"%(orr,ai,oii,ar)); return
        # Store only magnitudes and let the FMA variant carry the sign.  FFTW
        # reports 10-15% from this: it is not the arithmetic that changes, it is
        # that c and -c collapse to one constant, roughly halving the broadcast
        # table the codelet has to keep live.
        cc=s.const("c",abs(c)); ss=s.const("s",abs(sn))
        # real: ar*c - ai*s
        op = {(1,1):"V_FMSUB",(1,-1):"V_FMADD",(-1,1):"V_FNMSUB",(-1,-1):"V_FNMADD"}[
             (1 if c>=0 else -1, 1 if sn>=0 else -1)]
        s.emit("vf %s=%s(%s,%s,V_MUL(%s,%s));"%(orr,op,ar,cc,ai,ss))
        # imag: ar*s + ai*c
        op2= {(1,1):"V_FMADD",(1,-1):"V_FMSUB",(-1,1):"V_FNMADD",(-1,-1):"V_FNMSUB"}[
             (1 if sn>=0 else -1, 1 if c>=0 else -1)]
        s.emit("vf %s=%s(%s,%s,V_MUL(%s,%s));"%(oii,op2,ar,ss,ai,cc))
    def run(s,radices):
        n=s.n; N=n; sstride=1; cur=n
        A=("ar","ai"); B=("br","bi")
        X,Y=A,B; flips=0
        # A single-pass codelet does not READ ar - preload, tw and prod all
        # bring their inputs in another way - so it can write its result there
        # and keep the ping-pong parity even.  prod was left out of this test,
        # so fft8_prod alone landed its result in the SCRATCH pair and said so
        # in its return value, which efft_prod (and every other caller) ignores.
        # Nothing asked for an 8-point product codelet until the small-N path
        # did, and then band 128 came back as garbage.
        if (s.preload or s.tw or s.prod) and len(radices)==1: Y=A
        # Fused twiddle: multiply the inputs by runtime factors as they are read,
        # instead of a separate pass that re-reads and re-writes the whole block.
        pre={}
        if s.preload and not s.tw:
            for idx in range(n):
                pr,pi="p%d_r"%idx,"p%d_i"%idx
                s.emit("vf %s=ar[S*%d], %s=ai[S*%d];"%(pr,idx,pi,idx))
                pre[idx]=(pr,pi)
        if s.tw:
            for idx in range(n):
                pr,pi="p%d_r"%idx,"p%d_i"%idx
                if idx==0:
                    s.emit("vf %s=ar[0], %s=ai[0];"%(pr,pi))
                else:
                    s.emit("const vf W%dr=V_SET1(twr[%d]), W%di=V_SET1(twi[%d]);"%(idx,idx,idx,idx))
                    s.emit("vf %s=V_FMSUB(ar[S*%d],W%dr,V_MUL(ai[S*%d],W%di));"%(pr,idx,idx,idx,idx))
                    s.emit("vf %s=V_FMADD(ar[S*%d],W%di,V_MUL(ai[S*%d],W%dr));"%(pi,idx,idx,idx,idx))
                pre[idx]=(pr,pi)
        s.pre=pre
        for r in radices:
            m=cur//r
            for j in range(m):
                for q in range(sstride):
                    # load
                    ins=[]
                    for k in range(r):
                        idx=q+sstride*(j+m*k)
                        if s.pre and X is A:
                            ins.append(s.pre[idx])
                        elif s.prod and X is A:
                            # each element is read exactly once in the first pass
                            pr,pi="g%d_r"%s.nc,"g%d_i"%s.nc; s.nc+=1
                            s.emit("vf dR%d=V_LOADU(dr+DS*%d), dI%d=V_LOADU(di+DS*%d);"
                                   %(idx,idx,idx,idx))
                            s.emit("vf tR%d=V_LOADU(tr+DS*%d), tI%d=V_LOADU(ti+DS*%d);"
                                   %(idx,idx,idx,idx))
                            s.emit("vf %s=V_FMSUB(dR%d,tR%d,V_MUL(dI%d,tI%d));"
                                   %(pr,idx,idx,idx,idx))
                            # conj(d*t): the backward transform wants it, free here
                            s.emit("vf %s=V_FNMSUB(dR%d,tI%d,V_MUL(dI%d,tR%d));"
                                   %(pi,idx,idx,idx,idx))
                            ins.append((pr,pi))
                        else:
                            ins.append(("%s[S*%d]"%(X[0],idx),"%s[S*%d]"%(X[1],idx)))
                    outs=s.dft(r,ins)
                    for l in range(r):
                        c,sn=wconst(j*sstride*l, N)
                        o=("t%d_r"%s.nc,"t%d_i"%s.nc); s.nc+=1
                        s.cmul(outs[l][0],outs[l][1],c,sn,o)
                        idx=q+sstride*(r*j+l)
                        s.emit("%s[S*%d]=%s; %s[S*%d]=%s;"%(Y[0],idx,o[0],Y[1],idx,o[1]))
            X,Y=Y,X; flips^=1; cur=m; sstride*=r
        return flips
    def dft(s,r,ins):
        """emit an r-point DFT, return list of (re,im) names"""
        def nm():
            v=("u%d_r"%s.nc,"u%d_i"%s.nc); s.nc+=1; return v
        def add(a,b):
            o=nm(); s.emit("vf %s=V_ADD(%s,%s), %s=V_ADD(%s,%s);"%(o[0],a[0],b[0],o[1],a[1],b[1])); return o
        def sub(a,b):
            o=nm(); s.emit("vf %s=V_SUB(%s,%s), %s=V_SUB(%s,%s);"%(o[0],a[0],b[0],o[1],a[1],b[1])); return o
        def muli(a):   # multiply by -i  (DIF forward convention)
            o=nm(); s.emit("vf %s=%s, %s=V_SUB(Z,%s);"%(o[0],a[1],o[1],a[0])); return o
        if r==2:
            return [add(ins[0],ins[1]), sub(ins[0],ins[1])]
        if r==4:
            t0=add(ins[0],ins[2]); t1=sub(ins[0],ins[2])
            t2=add(ins[1],ins[3]); t3=muli(sub(ins[1],ins[3]))
            return [add(t0,t2), add(t1,t3), sub(t0,t2), sub(t1,t3)]
        if r==8:
            # radix-8 = two radix-4 on even/odd then combine with w8^k
            e=[ins[0],ins[2],ins[4],ins[6]]; o=[ins[1],ins[3],ins[5],ins[7]]
            E=s.dft(4,e); O=s.dft(4,o)
            res=[None]*8
            for k in range(4):
                c,sn=wconst(k,8)
                tw=("v%d_r"%s.nc,"v%d_i"%s.nc); s.nc+=1
                s.cmul(O[k][0],O[k][1],c,sn,tw)
                res[k]=add(E[k],tw); res[k+4]=sub(E[k],tw)
            return res
        raise Exception("radix %d"%r)

def build(n,radices,name,tw=False,preload=False,prod=False):
    g=Gen(n,name,tw,preload,prod); flip=g.run(radices)
    if (preload or tw or prod) and len(radices)==1: flip=0
    body="\n".join(g.L)
    cdefs="\n".join("  const vf %s=V_SET1(%sf);"%(v,k) for k,v in g.consts.items())
    if prod:
        # ar/ai are never read - the first pass comes from the spectra - but the
        # ping-pong still needs somewhere to land on an even number of stages.
        args=("const float*restrict dr,const float*restrict di,"
              "const float*restrict tr,const float*restrict ti,"
              "vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,"
              "const long S,const long DS")
    elif tw:
        args="vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S,const float*restrict twr,const float*restrict twi"
    else:
        args="vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S"
    sig=("static inline int %s(%s){\n"
         "  const vf Z=V_ZERO();\n%s\n%s\n  return %d;\n}\n")%(name,args,cdefs,body,flip)
    return sig


class SRGen(Gen):
    """Split-radix DIT codelet: one straight-line DAG for the whole n-point DFT
       instead of a sequence of Stockham stages.

       X[k]      = U[k]      + (w^k Z[k] + w^3k Z'[k])
       X[k+n/2]  = U[k]      - (w^k Z[k] + w^3k Z'[k])
       X[k+n/4]  = U[k+n/4]  - i(w^k Z[k] - w^3k Z'[k])
       X[k+3n/4] = U[k+n/4]  + i(w^k Z[k] - w^3k Z'[k])

       with U over the even inputs and Z, Z' over x[4m+1], x[4m+3].  All twiddles
       are compile-time constants here, so the trivial ones cost nothing, and every
       input is read once into a register - which is why the result can be written
       back in place."""
    def load(s,idx):
        if s.prod:
            # conj(d*t) formed as the inputs are read, exactly as Gen does --
            # but split-radix reads every input ONCE into a register and writes
            # back in place, so unlike the Stockham form there is no scratch
            # buffer for the product codelet to bounce through.
            o=("q%d_r"%idx,"q%d_i"%idx)
            s.emit("vf dR%d=V_LOADU(dr+DS*%d), dI%d=V_LOADU(di+DS*%d);"
                   %(idx,idx,idx,idx))
            s.emit("vf tR%d=V_LOADU(tr+DS*%d), tI%d=V_LOADU(ti+DS*%d);"
                   %(idx,idx,idx,idx))
            s.emit("vf %s=V_FMSUB(dR%d,tR%d,V_MUL(dI%d,tI%d));"%(o[0],idx,idx,idx,idx))
            s.emit("vf %s=V_FNMSUB(dR%d,tI%d,V_MUL(dI%d,tR%d));"%(o[1],idx,idx,idx,idx))
            return o
        if s.tw and idx!=0:
            o=("q%d_r"%idx,"q%d_i"%idx)
            s.emit("const vf W%dr=V_SET1(twr[%d]), W%di=V_SET1(twi[%d]);"%(idx,idx,idx,idx))
            s.emit("vf %s=V_FMSUB(ar[S*%d],W%dr,V_MUL(ai[S*%d],W%di));"%(o[0],idx,idx,idx,idx))
            s.emit("vf %s=V_FMADD(ar[S*%d],W%di,V_MUL(ai[S*%d],W%dr));"%(o[1],idx,idx,idx,idx))
            return o
        o=("q%d_r"%idx,"q%d_i"%idx)
        s.emit("vf %s=ar[S*%d], %s=ai[S*%d];"%(o[0],idx,o[1],idx))
        return o
    def nm(s):
        v=("u%d_r"%s.nc,"u%d_i"%s.nc); s.nc+=1; return v
    def add(s,a,b):
        o=s.nm(); s.emit("vf %s=V_ADD(%s,%s), %s=V_ADD(%s,%s);"%(o[0],a[0],b[0],o[1],a[1],b[1])); return o
    def sub(s,a,b):
        o=s.nm(); s.emit("vf %s=V_SUB(%s,%s), %s=V_SUB(%s,%s);"%(o[0],a[0],b[0],o[1],a[1],b[1])); return o
    def mi(s,a):      # * (-i)
        o=s.nm(); s.emit("vf %s=%s, %s=V_SUB(Z,%s);"%(o[0],a[1],o[1],a[0])); return o
    def pi_(s,a):     # * (+i)
        o=s.nm(); s.emit("vf %s=V_SUB(Z,%s), %s=%s;"%(o[0],a[1],o[1],a[0])); return o
    def twmul(s,a,k,n):
        c,sn=wconst(k,n)
        o=("t%d_r"%s.nc,"t%d_i"%s.nc); s.nc+=1
        s.cmul(a[0],a[1],c,sn,o); return o
    def rec(s,idxs):
        n=len(idxs)
        if n==1: return [s.load(idxs[0])]
        if n==2:
            a=s.load(idxs[0]); b=s.load(idxs[1])
            return [s.add(a,b), s.sub(a,b)]
        U=s.rec(idxs[0::2]); Zc=s.rec(idxs[1::4]); Zp=s.rec(idxs[3::4])
        X=[None]*n; q=n//4
        for k in range(q):
            t1=s.twmul(Zc[k],k,n); t2=s.twmul(Zp[k],3*k,n)
            su=s.add(t1,t2); df=s.sub(t1,t2)
            X[k]      = s.add(U[k],su)
            X[k+n//2] = s.sub(U[k],su)
            mdf = s.mi(df)                      # -i*(w^k Z - w^3k Z')
            X[k+q]    = s.add(U[k+q], mdf)
            X[k+3*q]  = s.sub(U[k+q], mdf)
        return X

def build_sr(n,name,tw=False,prod=False):
    g=SRGen(n,name,tw,False,prod)
    X=g.rec(list(range(n)))
    for k in range(n):
        g.emit("ar[S*%d]=%s; ai[S*%d]=%s;"%(k,X[k][0],k,X[k][1]))
    body="\n".join(g.L)
    cdefs="\n".join("  const vf %s=V_SET1(%sf);"%(v,k) for k,v in g.consts.items())
    if prod:
        args=("const float*restrict dr,const float*restrict di,"
              "const float*restrict tr,const float*restrict ti,"
              "vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,"
              "const long S,const long DS")
    elif tw:
        args="vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S,const float*restrict twr,const float*restrict twi"
    else:
        args="vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S"
    return ("static inline int %s(%s){\n  (void)br;(void)bi;\n  const vf Z=V_ZERO();\n%s\n%s\n  return 0;\n}\n"
            )%(name,args,cdefs,body)


def broadcast_codelet(source):
    # Preserve the established staged codelets byte-for-byte. Generating a
    # separate name avoids changing their compiler inlining/register choices.
    import re
    return re.sub(r"V_LOADU\((dr|di)\+DS\*(\d+)\)",
                  lambda m: "V_SET1(%s[(DS/AP_W)*%s])" % (m[1], m[2]), source)


if __name__=="__main__":
    out=["/* generated by gen.py - do not edit.  Width-neutral: the V_* macros in",
         "   simd-inl.h bind to whatever the target has, at AP_W lanes. */",
         "#include \"simd-inl.h\"","",
         "#if defined(AP_CODELETS_INL_H_) == defined(HWY_TARGET_TOGGLE)",
         "#ifdef AP_CODELETS_INL_H_","#undef AP_CODELETS_INL_H_",
         "#else","#define AP_CODELETS_INL_H_","#endif","",
         "HWY_BEFORE_NAMESPACE();","namespace ap {","namespace HWY_NAMESPACE {",""]
    out.append(build(8,[8],"fft8_42",preload=True))
    out.append(build(32,[8,4],"fft32_84"))
    out.append(build(16,[8,2],"fft16_44"))
    out.append(build(64,[8,8],"fft64_88"))
    # product-loading variants: the matched filter's first stage reads two
    # spectra and forms conj(d*t) inside the codelet, so the product never
    # reaches memory.  One per element size the four-step can ask for.
    for nn,rr in ((8,[8]),(16,[8,2]),(32,[8,4]),(64,[8,8])):
        out.append(build(nn,rr,"fft%d_prod"%nn,prod=True))
    # Split-radix at the sizes elemfft.h actually selects.  8 is served by
    # fft8_42 and fft8_tw, so fftsr8 was generated and never called.
    for nn in (16,32,64):
        out.append(build_sr(nn,"fftsr%d"%nn))
        out.append(build_sr(nn,"fftsr%d_tw"%nn,tw=True))
    # Split-radix PRODUCT codelets. The Stockham fft%d_prod forms above bounce
    # through the br/bi scratch pair between their two passes -- 32 vector
    # accesses at m=16, 128 at m=64 -- and in the pair-batched path that
    # scratch is indexed at the OUTPUT stride, so consecutive calls walk the
    # whole element buffer instead of one small block. Split-radix reads each
    # input once into a register and writes back in place, so the scratch
    # traffic is not reduced, it is DELETED.
    for nn in (16,32,64):
        out.append(build_sr(nn,"fftsr%d_prod"%nn,prod=True))
    # Twiddle-fused: only the sizes elemfft.h falls through to.  16 and 32
    # go to the split-radix variants, so fft16_tw and fft32_tw were dead.
    for (nn,rr) in ((8,[8]),(64,[8,8])):
        out.append(build(nn,rr,"fft%d_tw"%nn,tw=True))
    for nn,rr in ((8,[8]),(16,[8,2]),(32,[8,4]),(64,[8,8])):
        out.append(broadcast_codelet(build(nn,rr,"fft%d_prod_broadcast"%nn,prod=True)))
    for nn in (16,32,64):
        out.append(broadcast_codelet(build_sr(nn,"fftsr%d_prod_broadcast"%nn,prod=True)))
    out += ["}  // namespace HWY_NAMESPACE", "}  // namespace ap",
            "HWY_AFTER_NAMESPACE();", "", "#endif"]
    open("codelets-inl.h","w").write("\n".join(out))
    print("generated codelets-inl.h")
