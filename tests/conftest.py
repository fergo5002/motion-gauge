from __future__ import annotations

import pytest

from motion_gauge import examples


@pytest.fixture(scope="session")
def pages():
    """Paths to the bundled example pages and specs."""
    return examples.paths()


@pytest.fixture(scope="session")
def session():
    from motion_gauge.session import Session

    with Session(headed=False) as s:
        yield s


@pytest.fixture(scope="session")
def clock(session, pages):
    """A control reading of this machine's frame clock, taken on a known-good page. Some CI runners
    run headless Chromium's frame clock at 30 Hz; the gate rightly calls that degraded for real-time
    work, so tests that need a healthy clock skip there with the reading as the reason."""
    from motion_gauge import instrument

    page = session.open(pages["calm"])
    try:
        return instrument.gate(page, realtime=True)
    finally:
        page.context.close()


@pytest.fixture
def healthy_clock(clock):
    if not clock["ok"]:
        pytest.skip("this machine's headless frame clock failed its control reading: " + "; ".join(clock["reasons"]))
    return clock


# A planted fault in the measurement path: the document says it is hidden and requestAnimationFrame
# never calls back, which is what a background tab does to every frame-based probe.
HIDDEN = """
Object.defineProperty(Document.prototype, 'visibilityState', {get: function () { return 'hidden'; }});
Object.defineProperty(Document.prototype, 'hidden', {get: function () { return true; }});
window.requestAnimationFrame = function () { return 0; };
"""

# A visible page whose frame clock is throttled to about 2 Hz.
THROTTLED = """
(function () {
  window.requestAnimationFrame = function (cb) { return setTimeout(function () { cb(performance.now()); }, 500); };
})();
"""

# Layout reads that return nothing, as they do in a tab the browser is not laying out.
NO_LAYOUT = """
Object.defineProperty(HTMLElement.prototype, 'innerText', {get: function () { return ''; }});
"""

# getComputedStyle that reports a stale colour.
STALE_STYLE = """
(function () {
  var real = window.getComputedStyle;
  window.getComputedStyle = function (e, p) {
    var c = real.call(window, e, p);
    return new Proxy(c, {get: function (t, k) { return k === 'color' ? 'rgb(0, 0, 0)' : (typeof t[k] === 'function' ? t[k].bind(t) : t[k]); }});
  };
})();
"""
