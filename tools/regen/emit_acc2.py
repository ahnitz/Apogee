"""JSON from accuracy_v2.py -> the ACC2 rows the library reads."""
import json, sys, subprocess

HEAD = """# matchedfilter ACCURACY table -- false dismissal, measured
#
# commit  %s
# trials  %d injected per cell
#
# A property of the ALGORITHM, not of any machine.
#
# KEY: n, taps, snr, in-band fraction f, effective bandwidth B_eff, coarse
# margin. BAND IS NOT IN THE KEY. Measured at n=8192, f=0.99, B_eff=16, the
# dismissal across bands 256, 512, 1024 and 2048 is 1.64, 1.88, 1.77 and
# 1.75e-2 -- a 1.14x spread inside the error bars, across band/B_eff from 16
# to 128. A candidate band enters only through the (f, B_eff) at its own
# edge, which selection computes from the reference.
#
# B_eff is sampled ABSOLUTELY, not as a fraction of the band. The previous
# grid did the latter, which tied it to the variable that does not matter
# and left a floor near band/10 -- so it never reached the values real
# references have. The FIR-search reference sits at B_eff 1.1 at every band.
#
# The margin dominates: 90x across 0.97 to 1.00, against 1.6x for 16x of n
# and 1.14x across every band. It gets the finest ladder.
#
# Rates below about 3/trials are not resolved and read as 0.0; that is a
# resolution floor, not a demonstration of safety.
#
# ACC2 n K snr f beff margin dismissal
"""


def main(src, dst, trials):
    rows = [r for r in json.load(open(src)) if "error" not in r]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    seen = {}
    for r in rows:
        k = (r["n"], r["K"], round(r["snr"], 2), round(r["f"], 4),
             round(r.get("beff_act", r.get("beff")), 2), round(r["margin"], 3))
        seen[k] = r["dismissal"]
    with open(dst, "w") as fh:
        fh.write(HEAD % (commit, trials))
        for k in sorted(seen):
            fh.write("ACC2 %d %d %.2f %.4f %.2f %.3f %.4e\n" % (k + (seen[k],)))
    print("wrote %d rows to %s" % (len(seen), dst))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6000)
