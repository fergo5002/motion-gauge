"""Check a storyboard's rules (predicates) against the rendered page.

    motion-gauge predicates PAGE --spec SPEC.json [--out REPORT.json] [--headed] [--samples 25]

Exit 0 when every predicate holds, 1 when any fails, 2 when the instrument gate failed (the run
measured nothing) or the spec is invalid. The spec format is in the README.

Times are fractions of the beat's motion window: 0 is where the motion starts, 1 the settle. For a
seek spec that window is the beat's `window`; for a steps spec it is `window_ms` after `enter`.

  appearsBy(sel, t)          some element of sel is visible (shown, not ghosted, in the frame) by time t
  before(a, b)               every element of a has arrived (its box and opacity no longer change
                             before the settle) by the time the first element of b appears
  staysInFrame(sel)          every visible element of sel stays inside the frame, within 1 px, at
                             every sample of the window and at the settle (tol= to change the px)
  noOverlap(a, b)            at the settle no visible pair from a and b overlaps past IoU 0.2 (iou=)
  maxMovers(n)               no more than n elements move in any one sampling interval (of=window
                             counts every element that moves at any time in the window instead)
  density(max_cell=0.6)      no cell of the 6 by 8 coverage grid is over max_cell at the settle
                             (using=ink reads the pixels instead of the boxes)

A selector that matches nothing fails its predicate: a check that cannot see its subject has not
passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from motion_gauge import drive, instrument
from motion_gauge.session import Session

SPEC_ID = "motion-gauge/predicates/1"

# name: (positional parameters, keyword parameters with defaults)
KNOWN = {
    "appearsBy": (("sel", "t"), {}),
    "before": (("a", "b"), {}),
    "staysInFrame": (("sel",), {"tol": 1.0}),
    "noOverlap": (("a", "b"), {"iou": 0.2}),
    "maxMovers": (("n",), {"of": "peak"}),
    "density": ((), {"max_cell": 0.6, "using": "coverage"}),
}
NUMERIC = {"t", "n", "tol", "iou", "max_cell"}
SELECTORS = {"sel", "a", "b"}


@dataclass
class Predicate:
    name: str
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    text: str = ""

    def param(self, key: str):
        pos, kw = KNOWN[self.name]
        if key in pos:
            return self.args[pos.index(key)]
        return self.kwargs.get(key, kw.get(key))

    def selectors(self) -> list[str]:
        pos, _ = KNOWN[self.name]
        return [self.args[j] for j, p in enumerate(pos) if p in SELECTORS]


def _split(body: str) -> list[str]:
    """Split on commas outside brackets and quotes."""
    out, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced brackets")
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if quote or depth:
        raise ValueError("unbalanced brackets or quotes")
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _unquote(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def _value(key: str, raw: str):
    raw = _unquote(raw.strip())
    if key in NUMERIC:
        try:
            v = float(raw)
        except ValueError:
            raise ValueError(f"{key} must be a number, not {raw!r}") from None
        if key == "n":
            if v != int(v) or v < 0:
                raise ValueError(f"n must be a whole number, not {raw!r}")
            return int(v)
        return v
    return raw


def parse(text: str) -> Predicate:
    """`name(arg, arg, key=value)`, as written in a storyboard."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s*\((.*)\)\s*", text, re.S)
    if not m:
        raise ValueError(f"not a predicate: {text!r} (expected name(args))")
    name, body = m.group(1), m.group(2)
    if name not in KNOWN:
        raise ValueError(f"unknown predicate {name!r} in {text!r}; known: {', '.join(KNOWN)}")
    pos, kw = KNOWN[name]
    try:
        parts = _split(body)
    except ValueError as e:
        raise ValueError(f"{text!r}: {e}") from None
    args, kwargs, extra = [], {}, []
    for part in parts:
        km = re.fullmatch(r"([A-Za-z_]+)\s*=\s*(.+)", part, re.S)
        if km and km.group(1) in kw:
            kwargs[km.group(1)] = _value(km.group(1), km.group(2))
        elif len(args) < len(pos):
            args.append(_value(pos[len(args)], part))
        else:
            extra.append(part)
    names = [k for k in kw if k not in kwargs]
    for part in extra:   # density(0.5): a positional beyond the required ones fills the keywords in order
        if not names:
            raise ValueError(f"{text!r}: too many arguments for {name}")
        key = names.pop(0)
        kwargs[key] = _value(key, part)
    if len(args) != len(pos):
        raise ValueError(f"{text!r}: {name} takes {', '.join(pos)}")
    for p, v in zip(pos, args):
        if p in SELECTORS and not v:
            raise ValueError(f"{text!r}: an empty selector")
    if name == "maxMovers" and kwargs.get("of", "peak") not in ("peak", "window"):
        raise ValueError(f"{text!r}: of= is peak or window")
    if name == "density" and kwargs.get("using", "coverage") not in ("coverage", "ink"):
        raise ValueError(f"{text!r}: using= is coverage or ink")
    return Predicate(name, args, kwargs, text.strip())


def validate(spec: dict) -> dict:
    """Check the spec's shape and parse every predicate, so a typo fails before a browser starts."""
    drive.check_spec(spec)
    for j, row in enumerate(spec["beats"]):
        where = row.get("label") or f"beat {j}"
        preds = row.get("predicates", [])
        if not isinstance(preds, list):
            raise ValueError(f"{where}: predicates is a list of strings")
        for p in preds:
            try:
                parse(p)
            except ValueError as e:
                raise ValueError(f"{where}: {e}") from None
    return spec


# ---------------------------------------------------------------- evaluation

def _timeline(win: dict | None, final: dict, nsel: int) -> list[tuple[float, list[list[dict]]]]:
    """(time, per-selector element states) for every sample, the settle last at time 1 (0 for a
    beat with no window)."""
    out = []
    if win:
        for s in win.get("samples", []):
            out.append((s["at"], s["els"]["sets"]))
    out.append((1.0 if win else 0.0, final["sets"]))
    return out


def _same(e: dict | None, f: dict) -> bool:
    """Two readings of one element agree: visibility, opacity within 0.02, box within 0.75 px."""
    return (e is not None and e["shown"] == f["shown"] and abs(e["a"] - f["a"]) <= 0.02
            and all(abs(x - y) <= 0.75 for x, y in zip(e["box"], f["box"])))


def _appear(tl, j: int) -> float | None:
    """The first time any element of selector j is visible inside the frame."""
    for at, sets in tl:
        if any(e["shown"] and e["inview"] for e in sets[j]):
            return at
    return None


def _arrive(tl, j: int) -> tuple[float | None, list[str]]:
    """The latest time any element of selector j last changed before the settle, over the elements
    visible at the settle; None when none is visible at the settle."""
    final = {e["id"]: e for e in tl[-1][1][j]}
    shown = [i for i, e in final.items() if e["shown"]]
    if not shown:
        return None, []
    latest = tl[0][0]
    for i in shown:
        seq = [(at, {e["id"]: e for e in sets[j]}.get(i)) for at, sets in tl]
        t = seq[0][0]
        for k in range(len(seq) - 1, -1, -1):
            if not _same(seq[k][1], final[i]):
                t = seq[k + 1][0]
                break
        latest = max(latest, t)
    return latest, [final[i]["n"] for i in shown]


def _iou(p, q) -> float:
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    inter = ix * iy
    union = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - inter
    return inter / union if union > 0 else 0.0


def evaluate(p: Predicate, tl, index: dict[str, int], win: dict | None, settled: dict, W: float, H: float, ink: dict | None, where: str) -> dict:
    res = {"predicate": p.text, "ok": False, "detail": "", "values": {}}
    for sel in p.selectors():
        j = index[sel]
        if not any(sets[j] for _, sets in tl):
            res["detail"] = f"{sel} matches nothing in {where}"
            return res

    if p.name == "appearsBy":
        j, t = index[p.param("sel")], p.param("t")
        a = _appear(tl, j)
        res["values"] = {"appear": a, "by": t}
        res["ok"] = a is not None and a <= t + 1e-9
        res["detail"] = f"{p.param('sel')} " + ("never becomes visible" if a is None else f"appears at {a:.2f}, {'by' if res['ok'] else 'after'} {t:g}")
    elif p.name == "before":
        a, b = p.param("a"), p.param("b")
        arr, names = _arrive(tl, index[a])
        app = _appear(tl, index[b])
        res["values"] = {"arrive": arr, "appear": app}
        if arr is None:
            res["detail"] = f"{a} is not visible at the settle, so it never arrives"
        elif app is None:
            res["detail"] = f"{b} never becomes visible"
        else:
            res["ok"] = arr <= app + 1e-9
            res["detail"] = f"{a} arrives at {arr:.2f}; {b} appears at {app:.2f}"
    elif p.name == "staysInFrame":
        sel, tol = p.param("sel"), p.param("tol")
        worst, seen = (0.0, None), 0
        for at, sets in tl:
            for e in sets[index[sel]]:
                if not e["shown"]:
                    continue
                seen += 1
                l, t, r, b = e["box"]
                for over, side in ((-l, "left"), (-t, "top"), (r - W, "right"), (b - H, "bottom")):
                    if over > tol and over > worst[0]:
                        worst = (over, (e["n"], side, at))
        res["values"] = {"worst_px": round(worst[0], 1)}
        if not seen:
            res["detail"] = f"{sel} is never visible in {where}"
        elif worst[1]:
            n, side, at = worst[1]
            res["detail"] = f"{n} goes {worst[0]:.0f} px past the {side} edge of the frame at {at:.2f}"
        else:
            res["ok"] = True
            res["detail"] = f"{sel} stays inside the frame at all {len(tl)} samples"
    elif p.name == "noOverlap":
        a, b, lim = p.param("a"), p.param("b"), p.param("iou")
        fa = [e for e in tl[-1][1][index[a]] if e["shown"]]
        fb = [e for e in tl[-1][1][index[b]] if e["shown"]]
        if not fa or not fb:
            res["detail"] = f"{a if not fa else b} is not visible at the settle, so the overlap cannot be checked"
            return res
        best, pair = 0.0, None
        for x in fa:
            for y in fb:
                if x["id"] == y["id"]:
                    continue
                v = _iou(x["box"], y["box"])
                if v > best:
                    best, pair = v, (x["n"], y["n"])
        res["values"] = {"iou": round(best, 4), "pair": pair}
        res["ok"] = best <= lim + 1e-9
        res["detail"] = (f"{pair[0]} and {pair[1]} overlap at IoU {best:.3f}" if pair else "no overlap") + f" (limit {lim:g})"
    elif p.name == "maxMovers":
        n, of = p.param("n"), p.param("of")
        peak = win["peak"] if win else 0
        window = win["window"] if win else 0
        got = peak if of == "peak" else window
        res["values"] = {"peak": peak, "window": window, "limit": n}
        res["ok"] = got <= n
        res["detail"] = f"{got} elements move {'at once at most' if of == 'peak' else 'in the window'} (limit {n})" + (
            f": {win['names'][:8]}" if win and not res["ok"] else "")
    elif p.name == "density":
        lim, using = p.param("max_cell"), p.param("using")
        cells = settled["coverage"] if using == "coverage" else ink["cells"]
        top = max((v, r, c) for r, row in enumerate(cells) for c, v in enumerate(row))
        res["values"] = {"max_cell": top[0], "cell": [top[1], top[2]], "using": using}
        res["ok"] = top[0] <= lim + 1e-9
        res["detail"] = f"the densest cell (row {top[1]}, column {top[2]}) is {top[0]:.2f} covered (limit {lim:g}, by {using})"
    return res


def check(target, spec: dict, *, headed: bool = False, session: Session | None = None, extra_init=(), samples: int = 25,
          display_hz: float | None = None) -> dict:
    """Check every beat's predicates on the page at `target`. Returns the report as a dict."""
    spec = validate(spec)
    drive.check_samples(samples)
    own = session is None
    sess = session or Session(headed=headed).__enter__()
    started = time.time()
    try:
        page = sess.open(target, viewport=drive.viewport_for(spec), extra_init=extra_init)
        try:
            gate = instrument.gate(page, display_hz=display_hz)
            report = {"spec": SPEC_ID, "page": str(target), "measured": False, "ok": False, "gate": gate, "beats": [],
                      "kind": spec["kind"], "samples": samples, "headed": sess.headed}
            if not gate["ok"]:
                report["note"] = "the instrument gate failed before the run, so it measured nothing: " + "; ".join(gate["reasons"])
                return report
            d = drive.driver_for(page, spec)
            d.ready()
            beats = []
            for b in d.beats():
                preds = [parse(x) for x in b.row.get("predicates", [])]
                track = list(dict.fromkeys(s for p in preds for s in p.selectors()))
                bad = page.evaluate("ss => ss.map(s => { try { document.querySelector(s); return null; } catch (e) { return s; } })", track)
                bad = [s for s in bad if s]
                if bad:
                    beats.append({"label": b.label,
                                  "results": [{"predicate": p.text, "ok": False, "detail": f"invalid selector {bad}", "values": {}} for p in preds]})
                    continue
                d.prepare(b)
                win = d.window(b, samples, track)
                d.settle(b)
                settled = d.settled(b)
                final = d.boxes(b, track)
                ink = d.ink(settled["frame"]["view"]) if any(p.name == "density" and p.param("using") == "ink" for p in preds) else None
                tl = _timeline(win, final, len(track))
                index = {s: j for j, s in enumerate(track)}
                results = [evaluate(p, tl, index, win, settled, final["W"], final["H"], ink, b.label) for p in preds]
                beats.append({"label": b.label, "learns": b.row.get("learns"), "motion": b.row.get("motion"), "results": results,
                              "movers": None if win is None else {"window": win["window"], "peak": win["peak"], "names": win["names"]}})
            after = instrument.gate(page, display_hz=display_hz)
            report["gate_after"] = after
            report["errors"] = list(page.gauge_errors)
            if not after["ok"]:
                report["note"] = "the instrument gate failed after the run, so it measured nothing: " + "; ".join(after["reasons"])
                return report
            fails = sum(1 for b in beats for r in b["results"] if not r["ok"])
            report.update(measured=True, beats=beats, failures=fails, ok=fails == 0, seconds=round(time.time() - started, 1))
            return report
        finally:
            page.context.close()
    finally:
        if own:
            sess.__exit__(None, None, None)


def _print(report: dict) -> None:
    g = report["gate"]
    print(f"predicates: {report['page']} ({report.get('kind')}, {'headed' if report.get('headed') else 'headless'})")
    print(f"  gate: {g['verdict']}; {g['browser']} {g['version']}, rAF {g['raf_hz']} Hz against {g['display_hz']} Hz")
    if not report["measured"]:
        print("  " + report.get("note", "measured nothing"))
        return
    for b in report["beats"]:
        print(f"  {b['label']}" + (f": {b['learns']}" if b.get("learns") else ""))
        for r in b["results"]:
            print(f"    {'ok  ' if r['ok'] else 'FAIL'} {r['predicate']}: {r['detail']}")
    print(f"  {report['failures']} of {sum(len(b['results']) for b in report['beats'])} predicates failed")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="motion-gauge predicates", description="Check a storyboard's rules against the rendered page.")
    ap.add_argument("page", help="the page, as a path or URL")
    ap.add_argument("--spec", type=Path, required=True, help="the storyboard spec (JSON; see the README)")
    ap.add_argument("--out", type=Path, help="write the full report here (JSON)")
    ap.add_argument("--headed", action="store_true", help="a real window; needed for stepped pages, where cadence matters")
    ap.add_argument("--display-hz", type=float, help="the display's refresh rate, for headed runs")
    ap.add_argument("--samples", type=drive.samples_arg, default=25,
                    help="samples across each seeked motion window, at least 2 (default 25)")
    args = ap.parse_args(argv)
    try:
        spec = validate(json.loads(args.spec.read_text("utf8")))
    except (OSError, ValueError) as e:
        print(f"invalid spec: {e}")
        return 2
    report = check(args.page, spec, headed=args.headed, samples=args.samples, display_hz=args.display_hz)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1), "utf8")
    _print(report)
    if not report["measured"]:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
