"""busy on the example pages, whose counts are worked out by hand from their CSS."""
from __future__ import annotations

import json
import sys

import pytest

from motion_gauge import busy


@pytest.fixture(scope="module")
def spec(pages):
    return json.loads(pages["storyboard"].read_text("utf8"))


@pytest.fixture(scope="module")
def calm(pages, session, spec):
    return busy.measure(pages["calm"], spec, session=session)


@pytest.fixture(scope="module")
def noisy(pages, session, spec):
    return busy.measure(pages["busy"], spec, session=session)


def test_the_calm_page_is_measured_beat_by_beat(calm):
    assert calm["measured"] is True, calm.get("note")
    assert calm["kind"] == "seek"
    assert [b["label"] for b in calm["beats"]] == ["order arrives", "token rides", "shipped"]


def test_visible_text_runs_and_words_per_settled_beat(calm):
    # title (2 words) and the first card (2); the second card and its label are still at opacity 0
    # until the last beat, which adds "Shipped" (1) and "Checked by the warehouse" (4)
    assert [(b["text_runs"], b["words"]) for b in calm["beats"]] == [(2, 4), (2, 4), (4, 9)]


def test_lit_counts_painted_elements_that_are_visible(calm):
    # title, first card, token; then the second card and the label
    assert [b["lit"] for b in calm["beats"]] == [3, 3, 5]


def test_one_thing_moves_at_a_time_on_the_calm_page(calm):
    got = [(b["movers"]["window"], b["movers"]["peak"]) for b in calm["beats"]]
    # the card; the token; the second card then its label, never both at once
    assert got == [(1, 1), (1, 1), (2, 1)]


def test_everything_moves_at_once_on_the_busy_page(noisy):
    assert noisy["measured"] is True, noisy.get("note")
    got = [(b["movers"]["window"], b["movers"]["peak"]) for b in noisy["beats"]]
    # beat 1: title, first card, five sparks, the spinner; beat 2: token, sparks, spinner;
    # beat 3: second card, label, sparks, spinner
    assert got == [(8, 8), (7, 7), (8, 8)]
    assert all(b["loops"] == 1 for b in noisy["beats"])


def test_coverage_is_a_6_by_8_grid_and_the_calm_page_has_no_dense_cell(calm):
    for b in calm["beats"]:
        cells = b["coverage"]["cells"]
        assert len(cells) == 6 and all(len(r) == 8 for r in cells)
        assert b["coverage"]["over"] == [], b["label"]
        assert b["ink"]["over"] == [], b["label"]
        assert b["loops"] == 0


def test_a_dense_corner_is_flagged_by_boxes_and_by_pixels(noisy):
    b = noisy["beats"][0]
    corner = {(0, 6), (0, 7), (1, 6), (1, 7)}   # a 480 by 360 slab over 240 by 180 cells
    assert corner <= {(r, c) for r, c, _ in b["coverage"]["over"]}
    assert corner <= {(r, c) for r, c, _ in b["ink"]["over"]}
    assert b["coverage"]["max_cell"] == pytest.approx(1.0, abs=0.02)


def test_summary_per_metric(calm):
    s = calm["summary"]
    assert s["beats"] == 3
    assert s["words"]["max"] == 9 and s["words"]["min"] == 4
    assert s["movers_window"]["n"] == 3
    for key in busy.METRICS:
        assert {"n", "median", "mean", "p90", "max", "min"} <= set(s[key])


def test_a_timeline_can_be_any_expression_with_a_seek_method(pages, session, spec):
    own = dict(spec, timeline="({seek: t => document.getAnimations().forEach(a => { a.pause(); a.currentTime = t * 1000; })})")
    r = busy.measure(pages["calm"], own, session=session)
    assert r["measured"] is True, r.get("note")
    assert [(b["movers"]["window"], b["movers"]["peak"]) for b in r["beats"]] == [(1, 1), (1, 1), (2, 1)]


def test_a_stepped_page_is_sampled_in_real_time(pages, session, healthy_clock):
    spec = json.loads(pages["steps_spec"].read_text("utf8"))
    r = busy.measure(pages["steps"], spec, session=session)
    assert r["measured"] is True, r.get("note")
    assert r["kind"] == "steps"
    assert r["beats"][0]["movers"] is None
    assert [b["movers"]["window"] for b in r["beats"][1:]] == [2, 3]
    assert [b["text_runs"] for b in r["beats"]] == [1, 3, 6]


def test_a_page_with_no_spec_is_refused(pages, session):
    with pytest.raises(ValueError, match="spec"):
        busy.measure(pages["calm"], None, session=session)


def test_an_unknown_kind_is_refused(pages, session, spec):
    with pytest.raises(ValueError, match="kind"):
        busy.measure(pages["calm"], dict(spec, kind="film"), session=session)


# ---------------------------------------------------------------- --samples below 2

class _Page:
    """Records what a driver asks of the page; never opens a browser."""

    def __init__(self):
        self.calls = []

    def evaluate(self, js, arg=None):
        self.calls.append(js)
        return {}


@pytest.mark.parametrize("n", [1, 0])
def test_a_seeked_window_refuses_fewer_than_two_samples_before_touching_the_page(n):
    from motion_gauge import drive
    page = _Page()
    d = drive.SeekDriver(page, {"frame": "#frame", "timeline": "animations"})
    b = drive.Beat("b1", "#frame", row={"at": 1.0, "window": [0, 1.0]})
    with pytest.raises(ValueError, match="samples"):
        d.window(b, n, [])
    assert page.calls == []


@pytest.mark.parametrize("n", ["1", "0", "-3"])
def test_busy_refuses_fewer_than_two_samples_at_the_command_line(monkeypatch, capsys, n):
    monkeypatch.setattr(busy, "measure", lambda *a, **k: pytest.fail(f"measure ran with --samples {n}"))
    with pytest.raises(SystemExit) as e:
        busy.main(["page.html", "--spec", "spec.json", "--samples", n])
    assert e.value.code == 2
    assert "--samples" in capsys.readouterr().err


def test_a_run_that_crashes_exits_3(pages, tmp_path):
    import subprocess
    spec = json.loads(pages["storyboard"].read_text("utf8"))
    spec["frame"] = "#frmae"
    bad = tmp_path / "typo.json"
    bad.write_text(json.dumps(spec), "utf8")
    run = subprocess.run([sys.executable, "-m", "motion_gauge.busy", str(pages["calm"]), "--spec", str(bad)],
                         capture_output=True, text=True, timeout=300)
    assert run.returncode == 3, run.stdout + run.stderr
    assert "#frmae" in run.stdout
