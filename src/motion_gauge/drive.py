"""How the gauge moves a page to a beat and through its motion window.

Two drivers, one interface (`beats`, `prepare`, `window`, `settle`, `settled`, `boxes`, `ink`):

  seek    a page with a timeline it can seek. The spec's `timeline` is either "animations" (every
          Web Animation in the document, CSS animations and transitions included, paused and set to
          the same time) or a JavaScript expression for an object with a `seek(seconds)` method (a
          GSAP timeline, say). Each beat settles at `at` seconds; its motion window is `window`,
          [start, end] in seconds, sampled by seeking, so it does not depend on the frame rate.
  steps   a page that steps (a slide deck, a lab). Each beat may `go` (JavaScript run first, to
          reach the step before) and `enter` (JavaScript, or {"key": "ArrowRight"} dispatched on the
          document) to start its window. The window is real time, `window_ms` long, sampled every
          `every_ms`, so cadence matters here: run it headed and let the instrument gate say so.
"""

from __future__ import annotations

import argparse
import io
from dataclasses import dataclass, field

DEFAULT_READY = "() => document.readyState === 'complete' && (!document.fonts || document.fonts.status === 'loaded')"
TWO_FRAMES = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
INK_THRESHOLD = 40          # of 255, in any channel, away from the frame's commonest colour
ROWS, COLS = 6, 8
MIN_SAMPLES = 2             # a seeked window is sampled at its start and at its settle, so two at least
KINDS = ("seek", "steps")


def check_samples(n) -> int:
    """Refuse a sample count a seeked window cannot use (fewer than two divides by zero mid-run)."""
    if isinstance(n, bool) or not isinstance(n, int) or n < MIN_SAMPLES:
        raise ValueError(f"samples must be a whole number of at least {MIN_SAMPLES} "
                         f"(a window is sampled at its start and at its settle), not {n!r}")
    return n


def samples_arg(text: str) -> int:
    """argparse type for --samples, so a bad count stops the run before a browser opens."""
    try:
        return check_samples(int(text))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


@dataclass
class Beat:
    label: str
    frame: str
    row: dict = field(default_factory=dict)


class Driver:
    kind = ""

    def __init__(self, page, spec: dict | None = None) -> None:
        self.page = page
        self.spec = spec or {}

    def ready(self) -> None:
        self.page.wait_for_function(self.spec.get("ready") or DEFAULT_READY, timeout=20000)

    def prepare(self, b: Beat) -> None:
        pass

    def settled(self, b: Beat) -> dict:
        return self.page.evaluate("([f]) => __gauge.settled(f, {})", [b.frame])

    def boxes(self, b: Beat, sels: list[str]) -> dict:
        return self.page.evaluate("([f, s]) => __gauge.boxes(f, s, {})", [b.frame, sels])

    def ink(self, view: list[float]) -> dict:
        """The 6 by 8 grid read from pixels: each cell's share of pixels at least INK_THRESHOLD from
        the view's commonest colour in some channel."""
        import numpy as np
        from PIL import Image
        l, t, r, bt = view
        png = self.page.screenshot(clip={"x": l, "y": t, "width": r - l, "height": bt - t}, animations="allow")
        a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(np.int16)
        flat = a.reshape(-1, 3)
        q = (flat[:, 0].astype(np.int64) << 16) | (flat[:, 1].astype(np.int64) << 8) | flat[:, 2].astype(np.int64)
        vals, counts = np.unique(q, return_counts=True)
        bg = int(vals[counts.argmax()])
        bgc = np.array([(bg >> 16) & 255, (bg >> 8) & 255, bg & 255], dtype=np.int16)
        mask = (np.abs(a - bgc).max(axis=2) >= INK_THRESHOLD)
        h, w = mask.shape
        cells = []
        for ri in range(ROWS):
            row = []
            for ci in range(COLS):
                part = mask[round(ri * h / ROWS):round((ri + 1) * h / ROWS), round(ci * w / COLS):round((ci + 1) * w / COLS)]
                row.append(round(float(part.mean()), 3) if part.size else 0.0)
            cells.append(row)
        return {"cells": cells, "background": "#%06x" % bg}


class SeekDriver(Driver):
    kind = "seek"

    def beats(self) -> list[Beat]:
        frame = self.spec["frame"]
        return [Beat(r.get("label") or f"t={r['at']}", frame, row=r) for r in self.spec["beats"]]

    def _seek(self, t: float) -> None:
        tl = self.spec["timeline"]
        if tl == "animations":
            self.page.evaluate("t => { __gauge.seekAnimations(t); __gauge.finishTransitions(); }", t)
        else:
            self.page.evaluate("([tl, t]) => { (0, eval)('(' + tl + ')').seek(t); __gauge.finishTransitions(); }", [tl, t])

    def window(self, b: Beat, n: int, track: list[str]) -> dict | None:
        check_samples(n)
        w = b.row.get("window")
        if not w:
            return None
        t0, t1 = float(w[0]), float(w[1])
        self.page.evaluate("([r, t]) => __gauge.windowStart(r, t, {})", [b.frame, track])
        for j in range(n):
            f = j / (n - 1)
            self._seek(t0 + (t1 - t0) * f)
            self.page.evaluate("f => __gauge.sample(f)", f)
        return self.page.evaluate("() => __gauge.windowEnd()")

    def settle(self, b: Beat) -> None:
        self._seek(float(b.row["at"]))
        self.page.evaluate(TWO_FRAMES)


class StepsDriver(Driver):
    kind = "steps"

    def ready(self) -> None:
        super().ready()
        if self.spec.get("setup_wait_ms"):
            self.page.wait_for_timeout(int(self.spec["setup_wait_ms"]))
        if self.spec.get("setup"):
            self.page.evaluate(self.spec["setup"])

    def beats(self) -> list[Beat]:
        frame = self.spec["frame"]
        return [Beat(r.get("label") or f"position {j}", frame, row=r) for j, r in enumerate(self.spec["beats"])]

    def _rest(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)
        self.page.evaluate("() => __gauge.finishFinite()")
        self.page.evaluate(TWO_FRAMES)

    def prepare(self, b: Beat) -> None:
        if b.row.get("go"):
            self.page.evaluate(b.row["go"])
            self._rest(int(b.row.get("settle_ms", self.spec.get("settle_ms", 300))))

    def window(self, b: Beat, n: int, track: list[str]) -> dict | None:
        enter = b.row.get("enter")
        if not enter:
            return None
        ms = int(b.row.get("window_ms", self.spec.get("window_ms", 1500)))
        every = int(b.row.get("every_ms", self.spec.get("every_ms", 50)))
        return self.page.evaluate("([r, e, ms, ev, t]) => __gauge.recordWindow(r, e, ms, ev, t, {})",
                                  [b.frame, enter, ms, every, track])

    def settle(self, b: Beat) -> None:
        self._rest(int(b.row.get("settle_ms", self.spec.get("settle_ms", 300))))


def check_spec(spec: dict | None) -> dict:
    """The fields every driver needs, refused with a reason before a browser opens."""
    if not isinstance(spec, dict):
        raise ValueError("give a spec: a JSON object with kind, frame and beats (see the README)")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"the spec's kind is {kind!r}; it must be one of: {', '.join(KINDS)}")
    if not isinstance(spec.get("beats"), list) or not spec["beats"]:
        raise ValueError("a spec has a non-empty list of beats")
    if not spec.get("frame"):
        raise ValueError(f"a {kind} spec names its frame (a CSS selector)")
    if kind == "seek":
        if not spec.get("timeline"):
            raise ValueError('a seek spec names its timeline: "animations", or a JavaScript expression for an object with seek(seconds)')
        for j, row in enumerate(spec["beats"]):
            if "at" not in row:
                raise ValueError(f"{row.get('label') or f'beat {j}'}: a seek beat gives the time it settles at ('at')")
    return spec


def driver_for(page, spec: dict | None) -> Driver:
    spec = check_spec(spec)
    return SeekDriver(page, spec) if spec["kind"] == "seek" else StepsDriver(page, spec)


def viewport_for(spec: dict | None) -> tuple[int, int]:
    if spec and spec.get("viewport"):
        v = spec["viewport"]
        return int(v[0]), int(v[1])
    return 1920, 1080
