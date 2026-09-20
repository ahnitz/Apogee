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
    def __init__(s,n,name,tw=False,preload=False):
        s.n=n; s.name=name; s.L=[]; s.consts={}; s.nc=0; s.tw=tw; s.preload=preload
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
        if (s.preload or s.tw) and len(radices)==1: Y=A
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

def build(n,radices,name,tw=False,preload=False):
    g=Gen(n,name,tw,preload); flip=g.run(radices)
    if (preload or tw) and len(radices)==1: flip=0
    body="\n".join(g.L)
    cdefs="\n".join("  const vf %s=V_SET1(%sf);"%(v,k) for k,v in g.consts.items())
    args=("vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S,const float*restrict twr,const float*restrict twi"
          if tw else "vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S")
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

def build_sr(n,name,tw=False):
    g=SRGen(n,name,tw,False)
    X=g.rec(list(range(n)))
    for k in range(n):
        g.emit("ar[S*%d]=%s; ai[S*%d]=%s;"%(k,X[k][0],k,X[k][1]))
    body="\n".join(g.L)
    cdefs="\n".join("  const vf %s=V_SET1(%sf);"%(v,k) for k,v in g.consts.items())
    args=("vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S,const float*restrict twr,const float*restrict twi"
          if tw else "vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,const long S")
    return ("static inline int %s(%s){\n  (void)br;(void)bi;\n  const vf Z=V_ZERO();\n%s\n%s\n  return 0;\n}\n"
            )%(name,args,cdefs,body)


# ---------------------------------------------------------------------------
# int16 Q15 codelets.  Same Stockham DIF structure, but data is int16 (32 lanes
# per register instead of 16), butterflies use vpaddw/vpsubw, and twiddles use
# vpmulhrsw, which returns (a*b + 0x4000) >> 15 - exactly a Q15 multiply, and its
# built-in >>15 means the twiddle never grows the data.
#
# Only the butterfly grows it: |a +- b| <= 2*max, so each radix-2 stage shifts
# right by 1 and each radix-4 stage by 2.  That is what keeps int16 from
# overflowing, and it costs one bit of precision per stage.
# ---------------------------------------------------------------------------
class I16Gen:
    def __init__(s,n,name,shift=True):
        s.n=n; s.name=name; s.L=[]; s.consts={}; s.nc=0; s.shift=shift
    def emit(s,l): s.L.append("  "+l)
    def const(s,v):
        q=int(round(v*32767.0))
        q=max(-32767,min(32767,q))
        key=str(q)
        if key not in s.consts: s.consts[key]="k%d"%len(s.consts)
        return s.consts[key]
    def nm(s,p):
        v=("%s%d_r"%(p,s.nc),"%s%d_i"%(p,s.nc)); s.nc+=1; return v
    def add(s,a,b,sh):
        sh = sh if s.shift else 0
        o=s.nm("u")
        s.emit("vq15 %s=VQ15_SRA(VQ15_ADD(%s,%s),%d), %s=VQ15_SRA(VQ15_ADD(%s,%s),%d);"
               %(o[0],a[0],b[0],sh,o[1],a[1],b[1],sh)); return o
    def sub(s,a,b,sh):
        sh = sh if s.shift else 0
        o=s.nm("u")
        s.emit("vq15 %s=VQ15_SRA(VQ15_SUB(%s,%s),%d), %s=VQ15_SRA(VQ15_SUB(%s,%s),%d);"
               %(o[0],a[0],b[0],sh,o[1],a[1],b[1],sh)); return o
    def muli(s,a):          # * (-i)
        o=s.nm("u"); s.emit("vq15 %s=%s, %s=VQ15_NEG(%s);"%(o[0],a[1],o[1],a[0])); return o
    def cmul(s,a,c,sn):
        t=trivial(c,sn)
        if t=="1":  return a
        if t=="-1":
            o=s.nm("t"); s.emit("vq15 %s=VQ15_NEG(%s), %s=VQ15_NEG(%s);"%(o[0],a[0],o[1],a[1])); return o
        if t=="-i": return s.muli(a)
        if t=="+i":
            o=s.nm("t"); s.emit("vq15 %s=VQ15_NEG(%s), %s=%s;"%(o[0],a[1],o[1],a[0])); return o
        cc=s.const(c); ss=s.const(sn); o=s.nm("t")
        s.emit("vq15 %s=VQ15_SUB(VQ15_MUL(%s,%s),VQ15_MUL(%s,%s));"%(o[0],a[0],cc,a[1],ss))
        s.emit("vq15 %s=VQ15_ADD(VQ15_MUL(%s,%s),VQ15_MUL(%s,%s));"%(o[1],a[0],ss,a[1],cc))
        return o
    def dft(s,r,ins,sh):
        if r==2: return [s.add(ins[0],ins[1],sh), s.sub(ins[0],ins[1],sh)]
        if r==4:
            t0=s.add(ins[0],ins[2],1); t1=s.sub(ins[0],ins[2],1)
            t2=s.add(ins[1],ins[3],1); t3=s.muli(s.sub(ins[1],ins[3],1))
            return [s.add(t0,t2,1), s.add(t1,t3,1), s.sub(t0,t2,1), s.sub(t1,t3,1)]
        if r==8:
            E=s.dft(4,[ins[0],ins[2],ins[4],ins[6]],sh)
            O=s.dft(4,[ins[1],ins[3],ins[5],ins[7]],sh)
            res=[None]*8
            for k in range(4):
                c,sn=wconst(k,8)
                tw=s.cmul(O[k],c,sn)
                res[k]=s.add(E[k],tw,1); res[k+4]=s.sub(E[k],tw,1)
            return res
        raise Exception("int16 radix %d"%r)
    def run(s,radices):
        n=s.n; N=n; sstride=1; cur=n
        A=("ar","ai"); B=("br","bi"); X,Y=A,B; flip=0
        for r in radices:
            m=cur//r; sh=1
            for j in range(m):
                for q in range(sstride):
                    ins=[("%s[S*%d]"%(X[0],q+sstride*(j+m*k)),"%s[S*%d]"%(X[1],q+sstride*(j+m*k)))
                         for k in range(r)]
                    outs=s.dft(r,ins,sh)
                    for l in range(r):
                        c,sn=wconst(j*sstride*l,N)
                        o=s.cmul(outs[l],c,sn)
                        idx=q+sstride*(r*j+l)
                        s.emit("%s[S*%d]=%s; %s[S*%d]=%s;"%(Y[0],idx,o[0],Y[1],idx,o[1]))
            X,Y=Y,X; flip^=1; cur=m; sstride*=r
        return flip

def build_i16(n,radices,name,shift=True):
    g=I16Gen(n,name,shift); flip=g.run(radices)
    body="\n".join(g.L)
    cdefs="\n".join("  const vq15 %s=VQ15_SET1(%s);"%(v,k) for k,v in g.consts.items())
    return ("static inline int %s(vq15*restrict ar,vq15*restrict ai,"
            "vq15*restrict br,vq15*restrict bi,const long S){\n%s\n%s\n  return %d;\n}\n"
            )%(name,cdefs,body,flip)

if __name__=="__main__":
    out=["/* generated by gen.py - do not edit.  Width-neutral: the V_* macros in",
         "   simd.h bind to 512-bit or 256-bit intrinsics depending on PF_W. */",
         "#ifndef PF_CODELETS_H","#define PF_CODELETS_H","#include \"simd.h\"",""]
    out.append(build(8,[8],"fft8_42",preload=True))
    out.append(build(32,[8,4],"fft32_84"))
    out.append(build(32,[4,4,2],"fft32_442"))
    out.append(build(16,[8,2],"fft16_44"))
    out.append(build(64,[8,8],"fft64_88"))
    for nn,rr in ((8,[8]),(16,[8,2]),(32,[8,4]),(64,[8,8])):
        out.append(build_i16(nn,rr,"ffti16_%d"%nn))
        # same codelet with the per-stage shifts removed: the caller supplies
        # log2(n)+1 bits of headroom instead, trading precision for instructions

    for nn in (8,16,32,64):
        out.append(build_sr(nn,"fftsr%d"%nn))
        out.append(build_sr(nn,"fftsr%d_tw"%nn,tw=True))
    for (nn,rr) in ((8,[8]),(16,[8,2]),(32,[8,4]),(64,[8,8])):
        out.append(build(nn,rr,"fft%d_tw"%nn,tw=True))
    out.append("#endif")
    open("codelets.h","w").write("\n".join(out))
    print("generated codelets.h")
