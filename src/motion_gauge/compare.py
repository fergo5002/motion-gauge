"""Compare two busy reports, the one that should be calmer first.

    motion-gauge compare CALMER.json BUSIER.json [--json]

For each metric: both medians, and the pair share, the share of beat pairs (one from each report)
in which the calmer report's beat is lower, ties counted half. 0.6 or more is a hit, 0.4 or less a
miss the other way, anything between is no separation. Also the finished state (each report's last
beat), and a provisional band for each hit: the calmer report's 90th-percentile beat as a ceiling,
with its margin below the busier report's median. A band from two pages is a starting point for a
threshold, not a threshold.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from motion_gauge.busy import flat_row

PRIMARY = ("text_runs", "words", "lit", "coverage_max", "cells_over", "movers_window", "movers_peak")
OTHERS = ("coverage_mean", "ink_max", "ink_mean", "ink_over", "dim", "ghosts", "loops")
HIT, MISS = 0.6, 0.4


def pair_share(calm: list[float], busy: list[float]) -> float | None:
    if not calm or not busy:
        return None
    s = sum(1.0 if a < b else 0.5 if a == b else 0.0 for a in calm for b in busy)
    return s / (len(calm) * len(busy))


def verdict(share: float | None) -> str:
    if share is None:
        return "no data"
    return "hit" if share >= HIT else "miss" if share <= MISS else "no separation"


def p90(vals: list[float]) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, round(0.9 * (len(s) - 1))))]


def compare(calm: dict, busy: dict) -> dict:
    rc = [flat_row(b) for b in calm["beats"]]
    rb = [flat_row(b) for b in busy["beats"]]
    out = {"calm": calm["page"], "busy": busy["page"], "beats": [len(rc), len(rb)], "metrics": {}}
    for m in PRIMARY + OTHERS:
        a = [r[m] for r in rc if r[m] is not None]
        b = [r[m] for r in rb if r[m] is not None]
        share = pair_share(a, b)
        row = {"primary": m in PRIMARY, "n": [len(a), len(b)],
               "median": [statistics.median(a) if a else None, statistics.median(b) if b else None],
               "share": None if share is None else round(share, 3), "verdict": verdict(share),
               "final": [rc[-1][m] if rc else None, rb[-1][m] if rb else None]}
        if row["verdict"] == "hit":
            ceil = p90(a)
            med = row["median"][1]
            row["band"] = {"ceiling": ceil, "margin": med - ceil, "margin_share": round((med - ceil) / med, 3) if med else None} if ceil < med else None
        out["metrics"][m] = row
    return out


def markdown(res: dict) -> str:
    lines = ["| metric | median, calm | median, busy | pair share | verdict | finished state, calm / busy | band |",
             "|---|---|---|---|---|---|---|"]
    for m, r in res["metrics"].items():
        band = r.get("band")
        bt = "" if r["verdict"] != "hit" else ("none (ceiling not below the busy median)" if band is None else
                                                f"ceiling {band['ceiling']:g}, margin {band['margin']:g}"
                                                + (f" ({band['margin_share']:.0%} of the busy median)" if band["margin_share"] is not None else ""))
        name = m if r["primary"] else f"{m} (secondary)"
        lines.append(f"| {name} | {r['median'][0]} | {r['median'][1]} | {r['share']} | {r['verdict']} | {r['final'][0]} / {r['final'][1]} | {bt} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="motion-gauge compare", description="Compare two busy reports, the calmer first.")
    ap.add_argument("calm", type=Path)
    ap.add_argument("busy", type=Path)
    ap.add_argument("--json", action="store_true", help="print JSON instead of a Markdown table")
    args = ap.parse_args(argv)
    calm, busy = (json.loads(p.read_text("utf8")) for p in (args.calm, args.busy))
    for r, p in ((calm, args.calm), (busy, args.busy)):
        if not r.get("measured"):
            print(f"{p} measured nothing: {r.get('note')}")
            return 2
    res = compare(calm, busy)
    print(json.dumps(res, indent=1) if args.json else markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
