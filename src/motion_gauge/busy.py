"""How busy each settled beat is, read from the rendered page.

    motion-gauge busy PAGE --spec SPEC.json [--out BUSY.json] [--headed] [--samples 25]

The spec lists the beats (see the README; predicates are ignored here). Per beat it reports:

  text_runs, words   text a reader can see: visible, not ghosted, ink not transparent, inside the frame
  lit, dim, ghosts   painted elements (own text, a shape, an icon or image, a visible background or
                     border) that are visible and not ghosted; how many of those sit inside a .dim
                     element; how many painted elements are ghosts (inside a .ghost, or fainter than 0.2)
  coverage           a 6 by 8 grid over the frame, each cell's share covered by text line boxes and
                     painted non-text boxes; `over` lists cells above 0.6 as [row, column, share]
  ink                the same grid read from pixels, as a cross-check on coverage
  movers             elements whose own animated properties change in the beat's motion window:
                     `window` (any time in it) and `peak` (the most in one sampling interval)
  loops              endless animations running in the settled frame

The instrument gate runs before and after. If either fails, the run reports that it measured nothing.
Exit 0 measured, 2 measured nothing or an invalid spec, 3 the run itself failed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from motion_gauge import drive, instrument
from motion_gauge.session import Session

OVER = 0.6
METRICS = ("text_runs", "words", "lit", "dim", "ghosts", "coverage_max", "coverage_mean", "cells_over",
           "ink_max", "ink_mean", "ink_over", "movers_window", "movers_peak", "loops")


def _grid_summary(cells: list[list[float]]) -> dict:
    flat = [v for row in cells for v in row]
    return {"cells": cells, "max_cell": max(flat), "mean": round(sum(flat) / len(flat), 4),
            "over": [[r, c, v] for r, row in enumerate(cells) for c, v in enumerate(row) if v > OVER]}


def flat_row(b: dict) -> dict:
    m = b.get("movers")
    return {"text_runs": b["text_runs"], "words": b["words"], "lit": b["lit"], "dim": b["dim"], "ghosts": b["ghosts"],
            "coverage_max": b["coverage"]["max_cell"], "coverage_mean": b["coverage"]["mean"], "cells_over": len(b["coverage"]["over"]),
            "ink_max": b["ink"]["max_cell"], "ink_mean": b["ink"]["mean"], "ink_over": len(b["ink"]["over"]),
            "movers_window": m["window"] if m else None, "movers_peak": m["peak"] if m else None,
            "loops": b.get("loops")}


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "median": None, "mean": None, "p90": None, "max": None, "min": None}
    s = sorted(vals)
    p90 = s[min(len(s) - 1, max(0, round(0.9 * (len(s) - 1))))]
    return {"n": len(s), "median": statistics.median(s), "mean": round(statistics.fmean(s), 3), "p90": p90, "max": s[-1], "min": s[0]}


def summarise(beats: list[dict]) -> dict:
    rows = [flat_row(b) for b in beats]
    out = {"beats": len(beats)}
    for key in METRICS:
        out[key] = _stats([r[key] for r in rows if r[key] is not None])
    return out


def measure_beat(d: drive.Driver, b: drive.Beat, samples: int) -> dict:
    d.prepare(b)
    win = d.window(b, samples, [])
    d.settle(b)
    st = d.settled(b)
    ink = d.ink(st["frame"]["view"])
    return {"label": b.label,
            "text_runs": st["text_runs"], "words": st["words"], "lit": st["lit"], "dim": st["dim"], "ghosts": st["ghosts"],
            "coverage": _grid_summary(st["coverage"]), "ink": dict(_grid_summary(ink["cells"]), background=ink["background"]),
            "movers": None if win is None else {k: win[k] for k in ("window", "peak", "names", "intervals")},
            "loops": st["loops"], "frame": st["frame"], "texts": st["texts"]}


def measure(target, spec: dict | None, *, headed: bool = False, session: Session | None = None,
            extra_init=(), samples: int = 25, display_hz: float | None = None) -> dict:
    """Measure every beat in `spec` on the page at `target`. Returns the report as a dict."""
    drive.check_spec(spec)
    drive.check_samples(samples)
    own = session is None
    sess = session or Session(headed=headed).__enter__()
    started = time.time()
    try:
        page = sess.open(target, viewport=drive.viewport_for(spec), extra_init=extra_init)
        try:
            gate = instrument.gate(page, display_hz=display_hz, realtime=spec["kind"] == "steps")
            report = {"page": str(target), "measured": False, "gate": gate, "beats": [], "kind": spec["kind"],
                      "samples": samples, "headed": sess.headed}
            if not gate["ok"]:
                report["note"] = "the instrument gate failed before the run, so it measured nothing: " + "; ".join(gate["reasons"])
                return report
            d = drive.driver_for(page, spec)
            d.ready()
            beats = [measure_beat(d, b, samples) for b in d.beats()]
            after = instrument.gate(page, display_hz=display_hz, realtime=spec["kind"] == "steps")
            report["gate_after"] = after
            report["errors"] = list(page.gauge_errors)
            if not after["ok"]:
                report["note"] = ("the instrument gate failed after the run (the window was hidden or throttled while it measured), "
                                  "so it measured nothing: " + "; ".join(after["reasons"]))
                return report
            report.update(measured=True, beats=beats, summary=summarise(beats), seconds=round(time.time() - started, 1))
            return report
        finally:
            page.context.close()
    finally:
        if own:
            sess.__exit__(None, None, None)


def _print(report: dict) -> None:
    print(f"busy: {report['page']} ({report.get('kind')}, {'headed' if report.get('headed') else 'headless'})")
    g = report["gate"]
    print(f"  gate: {g['verdict']}; {g['browser']} {g['version']}, rAF {g['raf_hz']} Hz against {g['display_hz']} Hz, {g['renderer']}")
    if not report["measured"]:
        print("  " + report.get("note", "measured nothing"))
        return
    width = max([len(b["label"]) for b in report["beats"]] + [4]) + 2
    print(f"  {'beat':<{width}}{'runs':>6}{'words':>7}{'lit':>6}{'dim':>5}{'cov':>6}{'>.6':>5}{'ink':>6}{'mov':>5}{'peak':>6}{'loops':>7}")
    for b in report["beats"]:
        m = b["movers"]
        print(f"  {b['label']:<{width}}{b['text_runs']:>6}{b['words']:>7}{b['lit']:>6}{b['dim']:>5}{b['coverage']['max_cell']:>6.2f}"
              f"{len(b['coverage']['over']):>5}{b['ink']['max_cell']:>6.2f}{(m['window'] if m else '-'):>5}{(m['peak'] if m else '-'):>6}"
              f"{b['loops']:>7}")
    s = report["summary"]
    print("  median per beat: " + ", ".join(f"{k} {s[k]['median']}" for k in ("text_runs", "words", "lit", "coverage_max", "movers_window", "movers_peak")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="motion-gauge busy", description="How busy each settled beat is, read from the rendered page.")
    ap.add_argument("page", help="the page, as a path or URL")
    ap.add_argument("--spec", type=Path, required=True, help="the beats to measure (JSON; see the README)")
    ap.add_argument("--out", type=Path, help="write the full report here (JSON)")
    ap.add_argument("--headed", action="store_true", help="a real window; needed for stepped pages, where cadence matters")
    ap.add_argument("--display-hz", type=float, help="the display's refresh rate, for headed runs")
    ap.add_argument("--samples", type=drive.samples_arg, default=25,
                    help="samples across each seeked motion window, at least 2 (default 25)")
    args = ap.parse_args(argv)
    try:
        spec = drive.check_spec(json.loads(args.spec.read_text("utf8")))
    except (OSError, ValueError) as e:
        print(f"invalid spec: {e}")
        return 2
    try:
        report = measure(args.page, spec, headed=args.headed, samples=args.samples, display_hz=args.display_hz)
    except Exception as e:  # noqa: BLE001 - report a crash as a crash
        print(f"error: the run failed, so nothing was measured: {type(e).__name__}: {e}")
        return 3
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1), "utf8")
    _print(report)
    return 0 if report["measured"] else 2


if __name__ == "__main__":
    sys.exit(main())
