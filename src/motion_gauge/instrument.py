"""The instrument gate. Every probe calls it first, and again at the end of its run.

    motion-gauge instrument [PAGE] [--headed] [--display-hz HZ]

It answers one question: can this browser, on this page, measure anything? It runs the paste-in
`instrument_check.js` (the same file a person can paste into DevTools) and adds what only the
launcher knows: headed or headless, the browser's version, and the display rate. The page must be
visible, requestAnimationFrame must fire (raced against setTimeout, which still fires in a hidden
tab), its cadence must be within 10% of the display rate with no more than 10% long frames, and
style and layout reads must pass a control. A run whose gate fails reports that it measured nothing.

The display rate: headless Chromium draws at 60 Hz. Headed, it is `--display-hz` when given, read
from Windows when it can be, and otherwise the nearest standard rate to the measured one, which the
gate says it assumed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from functools import lru_cache

from motion_gauge.session import HERE, Session, session_of

SNIPPET = HERE / "instrument_check.js"
HEADLESS_HZ = 60.0


def snippet() -> str:
    """The paste-in instrument check, as text."""
    return SNIPPET.read_text("utf8")


@lru_cache(maxsize=1)
def os_display_hz() -> float | None:
    """The display's refresh rate where the OS will say it cheaply (Windows only), else None."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController | Measure-Object CurrentRefreshRate -Maximum).Maximum"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        hz = float(out)
        return hz if hz > 1 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def gate(page, headed: bool | None = None, display_hz: float | None = None, ms: int = 1000) -> dict:
    """Read the measurement path on `page`. `headed` defaults to how the page's session launched."""
    sess = session_of(page)
    if headed is None:
        headed = bool(sess and sess.headed)
    if display_hz:
        disp, source = float(display_hz), "given"
    elif not headed:
        disp, source = HEADLESS_HZ, "headless Chromium draws at 60 Hz"
    else:
        disp = os_display_hz()
        source = "read from Windows" if disp else None
    page.evaluate("o => { window.__instrumentCheck = o; }", {"displayHz": disp, "sampleMs": ms})
    try:
        raw = page.evaluate(snippet())
    finally:
        page.evaluate("() => { delete window.__instrumentCheck; }")
    cad = raw.get("cadence") or {}
    if not disp and cad.get("displayHz"):
        disp = cad["displayHz"]
        source = f"unknown; assumed {disp:g} Hz, the nearest standard rate to the measured one (pass --display-hz to set it)"
    reasons = list(raw.get("blockers") or [])
    ua_headless = "Headless" in (raw.get("ua") or "")
    if ua_headless == headed:
        reasons.append(f"launched {'headed' if headed else 'headless'} but the user agent says {'headless' if ua_headless else 'headed'}")
    browser = page.context.browser
    verdict = "INSTRUMENT DEGRADED" if reasons else raw.get("verdict")
    return {
        "ok": not reasons,
        "verdict": verdict,
        "reasons": reasons,
        "warnings": list(raw.get("warnings") or []),
        "visibility": raw.get("visibilityState"),
        "has_focus": raw.get("hasFocus"),
        "raf_fires": bool(raw.get("rafFires")),
        "frames": cad.get("frames", 0),
        "raf_hz": cad.get("rafHz"),
        "display_hz": disp,
        "display_source": source,
        "long_frame_share": cad.get("longFrameShare"),
        "headless": not headed,
        "ua_headless": ua_headless,
        "browser": browser.browser_type.name,
        "version": browser.version,
        "ua": raw.get("ua"),
        "renderer": raw.get("renderer"),
        "viewport": raw.get("viewport"),
        "dpr": raw.get("dpr"),
        "url": page.url,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="motion-gauge instrument",
                                 description="Check that the browser can measure this page at all.")
    ap.add_argument("page", nargs="?", help="a page to open, as a path or URL (default: about:blank)")
    ap.add_argument("--headed", action="store_true", help="a real window (needed wherever real-time cadence matters)")
    ap.add_argument("--display-hz", type=float, help="the display's refresh rate, when the gate cannot read it")
    ap.add_argument("--viewport", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    args = ap.parse_args(argv)
    w, h = (int(x) for x in args.viewport.lower().split("x"))
    with Session(headed=args.headed) as s:
        page = s.open(args.page or "about:blank", viewport=(w, h))
        g = gate(page, display_hz=args.display_hz)
    print(json.dumps(g, indent=2))
    return 0 if g["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
