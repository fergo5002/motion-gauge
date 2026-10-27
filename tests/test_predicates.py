"""predicates: the calm page passes the storyboard, and each fault on the busy page fails its own rule."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from motion_gauge import predicates


@pytest.fixture(scope="module")
def spec(pages):
    return json.loads(pages["storyboard"].read_text("utf8"))


@pytest.fixture(scope="module")
def noisy(pages, session, spec):
    return predicates.check(pages["busy"], spec, session=session)


def result(report, label, text):
    b = next(b for b in report["beats"] if b["label"] == label)
    return next(r for r in b["results"] if r["predicate"] == text)


# ---------------------------------------------------------------- the notation

def test_parse_keeps_selectors_whole():
    p = predicates.parse('noOverlap(".a, .b", [data-x="1,2"])')
    assert (p.name, p.args) == ("noOverlap", [".a, .b", '[data-x="1,2"]'])
    p = predicates.parse("noOverlap(.row > :is(.a, .b), #c)")
    assert p.args == [".row > :is(.a, .b)", "#c"]
    assert predicates.parse("appearsBy(#tok, 0.1)").args == ["#tok", 0.1]
    assert predicates.parse("density(max_cell=0.6)").kwargs == {"max_cell": 0.6}
    assert predicates.parse("density(0.5)").kwargs == {"max_cell": 0.5}
    assert predicates.parse("noOverlap(#a, #b, iou=0.1)").kwargs == {"iou": 0.1}


@pytest.mark.parametrize("bad", ["sparkle(#x)", "before(#a)", "maxMovers(many)", "appearsBy(#a, soon)", "noOverlap(#a, #b",
                                 "maxMovers(2, of=often)", "density(using=vibes)"])
def test_parse_refuses_what_it_cannot_check(bad):
    with pytest.raises(ValueError):
        predicates.parse(bad)


@pytest.mark.parametrize("bad, words", [
    ({"kind": "seek", "frame": "#f", "timeline": "animations", "beats": [{"at": 1, "predicates": ["sparkle(#x)"]}]}, "sparkle"),
    ({"kind": "seek", "frame": "#f", "beats": [{"at": 1}]}, "timeline"),
    ({"kind": "seek", "timeline": "animations", "beats": [{"at": 1}]}, "frame"),
    ({"kind": "seek", "frame": "#f", "timeline": "animations", "beats": [{"window": [0, 1]}]}, "at"),
    ({"kind": "film", "frame": "#f", "beats": [{"at": 1}]}, "kind"),
    ({"frame": "#f", "beats": [{"at": 1}]}, "kind"),
    ({"kind": "steps", "frame": "#f", "beats": []}, "beats"),
])
def test_a_bad_spec_is_refused_before_anything_runs(bad, words):
    with pytest.raises(ValueError, match=words):
        predicates.validate(bad)


# ---------------------------------------------------------------- the calm page

def test_the_calm_page_passes_every_rule(pages, session, spec):
    r = predicates.check(pages["calm"], spec, session=session)
    assert r["measured"] is True, r.get("note")
    bad = [x for b in r["beats"] for x in b["results"] if not x["ok"]]
    assert bad == []
    assert r["ok"] is True and r["failures"] == 0
    assert sum(len(b["results"]) for b in r["beats"]) == 10


# ---------------------------------------------------------------- the busy page's faults

def test_a_title_that_leaves_the_frame_fails(noisy):
    r = result(noisy, "order arrives", "staysInFrame(#title)")
    assert r["ok"] is False and "right" in r["detail"]


def test_too_many_movers_fail(noisy):
    r = result(noisy, "order arrives", "maxMovers(2)")
    assert r["ok"] is False and r["values"]["peak"] == 8
    assert result(noisy, "token rides", "maxMovers(1)")["ok"] is False


def test_a_dense_corner_fails_density(noisy):
    r = result(noisy, "order arrives", "density(max_cell=0.6)")
    assert r["ok"] is False and r["values"]["max_cell"] == pytest.approx(1.0, abs=0.02)


def test_a_label_that_appears_before_its_card_arrives_fails(noisy):
    r = result(noisy, "shipped", "before(#card-b, #lbl)")
    assert r["ok"] is False
    assert r["values"]["arrive"] > r["values"]["appear"]


def test_cards_overlapping_past_iou_0_2_fail(noisy):
    r = result(noisy, "shipped", "noOverlap(#card-a, #card-b)")
    assert r["ok"] is False and r["values"]["iou"] == pytest.approx(1 / 3, abs=0.01)


def test_the_rules_the_busy_page_keeps_still_pass(noisy):
    for label, text in (("order arrives", "appearsBy(#card-a, 0.5)"), ("token rides", "appearsBy(#token, 0.1)"),
                        ("token rides", "staysInFrame(#token)"), ("shipped", "appearsBy(#lbl, 1)")):
        assert result(noisy, label, text)["ok"] is True, (label, text)
    assert noisy["failures"] == 6


def test_a_selector_that_matches_nothing_fails_rather_than_passing(pages, session, spec):
    own = dict(spec, beats=[dict(spec["beats"][0], predicates=["staysInFrame(#nothing-here)"])])
    r = predicates.check(pages["calm"], own, session=session)
    res = r["beats"][0]["results"][0]
    assert res["ok"] is False and "matches nothing" in res["detail"]


def test_an_invalid_selector_fails_its_rules(pages, session, spec):
    own = dict(spec, beats=[dict(spec["beats"][0], predicates=["staysInFrame(#1bad)"])])
    r = predicates.check(pages["calm"], own, session=session)
    res = r["beats"][0]["results"][0]
    assert res["ok"] is False and "invalid selector" in res["detail"]


def test_a_stepped_page_checks_its_rules(pages, session):
    spec = json.loads(pages["steps_spec"].read_text("utf8"))
    r = predicates.check(pages["steps"], spec, session=session)
    assert r["measured"] is True, r.get("note")
    assert r["ok"] is True, [x for b in r["beats"] for x in b["results"] if not x["ok"]]


# ---------------------------------------------------------------- the command line

@pytest.mark.parametrize("n", ["1", "0", "-3"])
def test_predicates_refuses_fewer_than_two_samples_at_the_command_line(monkeypatch, capsys, pages, n):
    monkeypatch.setattr(predicates, "check", lambda *a, **k: pytest.fail(f"check ran with --samples {n}"))
    with pytest.raises(SystemExit) as e:
        predicates.main([str(pages["calm"]), "--spec", str(pages["storyboard"]), "--samples", n])
    assert e.value.code == 2
    assert "--samples" in capsys.readouterr().err


def test_the_command_line_exits_0_on_the_calm_page_and_1_on_the_busy_one(pages, tmp_path):
    codes = {}
    for name in ("calm", "busy"):
        out = tmp_path / f"{name}.json"
        run = subprocess.run([sys.executable, "-m", "motion_gauge.predicates", str(pages[name]), "--spec", str(pages["storyboard"]),
                              "--out", str(out)], capture_output=True, text=True, timeout=300)
        codes[name] = run.returncode
        report = json.loads(out.read_text("utf8"))
        assert report["measured"] is True, run.stdout + run.stderr
    assert codes == {"calm": 0, "busy": 1}


def test_the_command_line_exits_2_on_a_bad_spec(tmp_path, pages, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"kind": "seek", "beats": []}), "utf8")
    assert predicates.main([str(pages["calm"]), "--spec", str(bad)]) == 2
    assert "invalid spec" in capsys.readouterr().out
