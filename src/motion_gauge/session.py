"""One browser for a run, and pages opened with the gauge's probe installed before the page's scripts."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe.js"

# Which session opened which context, so the instrument gate can say whether it was headed.
_OPENED: dict[int, "Session"] = {}


def url_of(target) -> str:
    """A URL for a page given as a URL or as a path on disk."""
    s = str(target)
    if s.startswith(("http://", "https://", "file:", "about:", "data:")):
        return s
    p = Path(s).resolve()
    if not p.exists():
        raise FileNotFoundError(f"no such page: {p}")
    return p.as_uri()


class Session:
    """Playwright and one Chromium browser, headless unless `headed`."""

    def __init__(self, headed: bool = False) -> None:
        self.headed = headed
        self.pw = None
        self.browser = None

    def __enter__(self) -> "Session":
        self.pw = sync_playwright().start()
        try:
            self.browser = self.pw.chromium.launch(headless=not self.headed)
        except Exception:
            self.pw.stop()
            raise
        return self

    def __exit__(self, *exc) -> None:
        for k in [k for k, v in _OPENED.items() if v is self]:
            _OPENED.pop(k, None)
        try:
            self.browser.close()
        finally:
            self.pw.stop()

    @property
    def version(self) -> str:
        return self.browser.version

    def open(self, target, viewport=(1920, 1080), extra_init=(), reduced_motion: str = "no-preference", wait: str = "load"):
        """A fresh context and page at `viewport`, the probe installed, then the page loaded.
        `extra_init` scripts run after the probe and before the page (the tests plant faults this way)."""
        ctx = self.browser.new_context(viewport={"width": int(viewport[0]), "height": int(viewport[1])},
                                       device_scale_factor=1, reduced_motion=reduced_motion)
        ctx.add_init_script(path=str(PROBE))
        for s in extra_init:
            ctx.add_init_script(script=s)
        _OPENED[id(ctx)] = self
        page = ctx.new_page()
        page.gauge_errors = []
        page.on("pageerror", lambda e: page.gauge_errors.append(str(e)))
        page.goto(url_of(target), wait_until=wait)
        return page


def session_of(page) -> Session | None:
    return _OPENED.get(id(page.context))
