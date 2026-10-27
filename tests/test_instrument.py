"""The instrument check and gate: a probe that cannot see the page must say it measured nothing."""
from __future__ import annotations

import json
import time

import pytest
from conftest import HIDDEN, NO_LAYOUT, STALE_STYLE, THROTTLED

from motion_gauge import instrument


def run_snippet(page, opts=None):
    """Evaluate the paste-in file exactly as a person would paste it, after setting its options."""
    if opts is not None:
        page.evaluate("o => { window.__instrumentCheck = o; }", opts)
    return page.evaluate(instrument.snippet())


@pytest.fixture
def open_page(session, pages):
    opened = []

    def _open(name="calm", extra_init=()):
        p = session.open(pages[name], extra_init=extra_init)
        opened.append(p)
        return p

    yield _open
    for p in opened:
        p.context.close()


def test_the_snippet_is_one_pasteable_expression():
    js = instrument.snippet()
    assert js.lstrip().startswith("/*")
    assert js.rstrip().endswith("})(window.__instrumentCheck);")


def test_the_snippet_passes_a_visible_page(open_page):
    out = run_snippet(open_page())
    assert out["blockers"] == [], out["blockers"]
    assert out["verdict"] in ("CLEAR", "USABLE WITH CAVEATS")
    assert out["visibilityState"] == "visible"
    assert out["rafFires"] is True
    assert out["cadence"]["frames"] >= 20
    assert out["layoutControl"] == {"innerText": "instrument control", "height": pytest.approx(out["layoutControl"]["height"])}
    assert out["layoutControl"]["height"] > 0


def test_the_snippet_degrades_on_a_hidden_tab_and_does_not_hang(open_page):
    page = open_page(extra_init=[HIDDEN])
    t0 = time.monotonic()
    out = run_snippet(page)
    assert time.monotonic() - t0 < 5
    assert out["verdict"] == "INSTRUMENT DEGRADED"
    assert out["rafFires"] is False
    assert any("hidden" in b for b in out["blockers"])
    assert any("requestAnimationFrame did not fire" in b for b in out["blockers"])


def test_the_snippet_degrades_on_a_throttled_frame_clock(open_page):
    out = run_snippet(open_page(extra_init=[THROTTLED]))
    assert out["verdict"] == "INSTRUMENT DEGRADED"
    assert out["visibilityState"] == "visible"
    assert any("frame intervals" in b for b in out["blockers"]), out["blockers"]


def test_the_snippet_degrades_when_layout_reads_come_back_empty(open_page):
    out = run_snippet(open_page(extra_init=[NO_LAYOUT]))
    assert out["verdict"] == "INSTRUMENT DEGRADED"
    assert any("Layout reads failed" in b for b in out["blockers"]), out["blockers"]


def test_the_snippet_degrades_when_computed_style_disagrees_with_what_was_set(open_page):
    out = run_snippet(open_page(extra_init=[STALE_STYLE]))
    assert out["verdict"] == "INSTRUMENT DEGRADED"
    assert any("getComputedStyle failed" in b for b in out["blockers"]), out["blockers"]


def test_the_snippet_warns_about_quirks_mode_but_not_on_a_standards_page(session, open_page, tmp_path):
    assert not any("Quirks" in w for w in run_snippet(open_page())["warnings"])
    p = tmp_path / "quirks.html"
    p.write_text("<html><body><p>no doctype</p></body></html>", "utf8")
    page = session.open(p)
    try:
        out = run_snippet(page)
    finally:
        page.context.close()
    assert out["blockers"] == []
    assert any("Quirks" in w for w in out["warnings"])
    assert out["verdict"] == "USABLE WITH CAVEATS"


@pytest.mark.parametrize("intervals, display, ok", [
    ([16.7] * 60, 60, True),                       # a healthy 60 Hz page
    ([33.3] * 60, 60, False),                      # half rate: throttled or overloaded
    ([16.7] * 45 + [50.0] * 15, 60, False),        # a quarter of the frames long
    ([8.33] * 120, 120, True),                     # a 120 Hz display
    ([16.7] * 5, 60, False),                       # too few frames to judge
    ([8.33] * 120, None, True),                    # unknown display: assumes 120 Hz, the nearest standard
    ([500.0] * 25, None, False),                   # unknown display at 2 Hz: off every standard rate
])
def test_cadence_rules(open_page, intervals, display, ok):
    opts = {"intervals": intervals}
    if display:
        opts["displayHz"] = display
    out = run_snippet(open_page(), opts)
    cadence_blocked = any(("Hz" in b or "frame" in b) for b in out["blockers"])
    assert cadence_blocked is (not ok), out["blockers"]


def test_the_gate_passes_a_visible_page_and_records_the_browser(open_page):
    g = instrument.gate(open_page())
    assert g["ok"] is True, g["reasons"]
    assert g["verdict"] in ("CLEAR", "USABLE WITH CAVEATS")
    assert g["visibility"] == "visible" and g["raf_fires"] is True
    assert g["headless"] is True and g["ua_headless"] is True
    assert g["browser"] == "chromium" and g["version"]
    assert g["display_hz"] == 60 and "headless" in g["display_source"]
    assert abs(g["raf_hz"] - 60) / 60 <= 0.1
    assert g["renderer"]
    json.dumps(g)


def test_the_gate_fails_a_hidden_page(open_page):
    g = instrument.gate(open_page(extra_init=[HIDDEN]))
    assert g["ok"] is False
    assert g["verdict"] == "INSTRUMENT DEGRADED"
    assert g["visibility"] == "hidden" and g["raf_fires"] is False
    assert any("hidden" in r for r in g["reasons"])


def test_a_run_whose_gate_fails_reports_that_it_measured_nothing(session, pages):
    from motion_gauge import busy, predicates
    spec = json.loads(pages["storyboard"].read_text("utf8"))
    r = busy.measure(pages["calm"], spec, session=session, extra_init=[HIDDEN])
    assert r["measured"] is False and r["beats"] == [] and r["gate"]["ok"] is False
    assert "measured nothing" in r["note"]
    p = predicates.check(pages["calm"], spec, session=session, extra_init=[HIDDEN])
    assert p["measured"] is False and p["beats"] == [] and p["ok"] is False
