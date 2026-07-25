#!/usr/bin/env python3
"""Threshold analysis for pixstudy rows.

The decisive population is rows where the pipeline had NO read of the field
(pix would fill it at harvest rank); rows where the pipeline read it matter
only through agreement. Prints precision/coverage per field across a
(margin, ncc) gate grid, split by population.
"""
import argparse
import glob
import json
from collections import defaultdict

MARGINS = (0.0, 0.02, 0.05, 0.08, 0.12, 0.20)
NCCS = (0.45, 0.55, 0.65, 0.75)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="/tmp/pixstudy")
    ap.add_argument("--field", default=None)
    args = ap.parse_args()

    rows = []
    for f in glob.glob(f"{args.rows}/rows_*.jsonl"):
        rows.extend(json.loads(l) for l in open(f))
    print(f"{len(rows)} rows")

    by_field = defaultdict(list)
    for r in rows:
        if r["pix_ok"] is None:
            continue
        by_field[r["field"]].append(r)

    for field, rs in sorted(by_field.items()):
        if args.field and field != args.field:
            continue
        unread = [r for r in rs if not r["pipe_had_read"]]
        read_wrong = [r for r in rs if r["pipe_had_read"] and r["pipe_ok"] is False]
        print(f"\n=== {field}: {len(rs)} rows | pipeline-unread {len(unread)} "
              f"| pipeline-read-wrong {len(read_wrong)}")
        for pop, name in ((unread, "UNREAD"), (read_wrong, "READ-WRONG"), (rs, "ALL")):
            if not pop:
                continue
            print(f"  [{name}]")
            for m in MARGINS:
                cells = []
                for a in NCCS:
                    sel = [r for r in pop if r["margin"] >= m and r["ncc"] >= a]
                    if not sel:
                        cells.append("      —      ")
                        continue
                    ok = sum(1 for r in sel if r["pix_ok"])
                    cells.append(f"{ok}/{len(sel)}={ok/len(sel):4.0%}".rjust(13))
                print(f"    m>={m:0.2f} " + " ".join(cells))
            agr = [r for r in pop if r.get("ctc_agree")]
            if agr:
                ok = sum(1 for r in agr if r["pix_ok"])
                print(f"    +CTC-agree (no pix gate): {ok}/{len(agr)}={ok/len(agr):.0%}")
                for m in (0.02, 0.05):
                    sel = [r for r in agr if r["margin"] >= m]
                    if sel:
                        ok = sum(1 for r in sel if r["pix_ok"])
                        print(f"    +CTC-agree & m>={m}: {ok}/{len(sel)}={ok/len(sel):.0%}")
            if field in ("risk_flags", "fee_status"):
                _directional(pop, name, field)
        print(f"    (ncc gates: {NCCS})")


DISQ = {"memory_tampering", "planetary_embargo", "active_warrant", "biohazard_red"}


def _directional(pop, name, field):
    """Deny/approve-direction precision: what the decision layer actually
    consumes. A partial flag read that includes a real disqualifying flag is a
    correct DENY signal even when the full set mismatches."""
    def flags(v):
        return set(str(v).split("|")) - {"none", ""}
    for m in (0.05, 0.12, 0.20):
        sel = [r for r in pop if r["margin"] >= m]
        if field == "risk_flags":
            deny = [r for r in sel if flags(r["pix"]) & DISQ]
            dok = sum(1 for r in deny if flags(r["truth"]) & DISQ)
            appr = [r for r in sel if r["pix"] == "none"]
            aok = sum(1 for r in appr if r["truth"] in ("none", ""))
        else:
            deny = [r for r in sel if r["pix"] in ("unpaid", "unknown")]
            dok = sum(1 for r in deny if r["truth"] == r["pix"])
            appr = [r for r in sel if r["pix"] in ("paid", "waived")]
            aok = sum(1 for r in appr if r["truth"] == r["pix"])
        if deny or appr:
            print(f"    [{name}] m>={m}: deny-dir {dok}/{len(deny)}"
                  f"{f'={dok/len(deny):.0%}' if deny else ''} | "
                  f"approve-dir {aok}/{len(appr)}"
                  f"{f'={aok/len(appr):.0%}' if appr else ''}")


if __name__ == "__main__":
    main()
