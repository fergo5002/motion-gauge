"""compare's scoring, on numbers worked out by hand, and on the two example pages."""
from __future__ import annotations

import json

from motion_gauge import busy, compare


def test_pair_share_counts_ties_half():
    assert compare.pair_share([1, 2], [3, 4]) == 1.0
    assert compare.pair_share([3, 4], [1, 2]) == 0.0
    assert compare.pair_share([2], [2]) == 0.5
    assert compare.pair_share([1, 3], [2]) == 0.5
    assert compare.pair_share([], [1]) is None


def test_verdict_thresholds():
    assert compare.verdict(0.6) == "hit"
    assert compare.verdict(0.59) == "no separation"
    assert compare.verdict(0.41) == "no separation"
    assert compare.verdict(0.4) == "miss"
    assert compare.verdict(None) == "no data"


def _report(values):
    beats = []
    for k, v in enumerate(values):
        grid = {"max_cell": 0.5, "mean": 0.1, "over": []}
        beats.append({"label": f"beat {k}", "text_runs": v, "words": v, "lit": v, "dim": 0,
                      "ghosts": 0, "coverage": grid, "ink": grid, "movers": None, "loops": 0})
    return {"page": "x", "measured": True, "beats": beats}


def test_a_band_is_set_only_below_the_busier_median():
    res = compare.compare(_report([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), _report([20, 21, 22, 23, 24]))
    w = res["metrics"]["words"]
    assert w["verdict"] == "hit" and w["share"] == 1.0
    assert w["band"] == {"ceiling": 9, "margin": 13, "margin_share": round(13 / 22, 3)}
    overlap = compare.compare(_report([1, 2, 3, 30]), _report([4, 5, 6]))["metrics"]["words"]
    assert overlap["verdict"] == "hit" and overlap["band"] is None


def test_the_calm_page_is_calmer_than_the_busy_page_on_movers(pages, session):
    spec = json.loads(pages["storyboard"].read_text("utf8"))
    calm = busy.measure(pages["calm"], spec, session=session)
    noisy = busy.measure(pages["busy"], spec, session=session)
    res = compare.compare(calm, noisy)
    assert res["metrics"]["movers_peak"]["verdict"] == "hit"
    assert res["metrics"]["movers_window"]["verdict"] == "hit"
    assert res["metrics"]["coverage_max"]["verdict"] == "hit"
    assert "| movers_peak |" in compare.markdown(res)


def test_compare_refuses_a_report_that_measured_nothing(tmp_path, capsys):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_report([1, 2])), "utf8")
    nothing = tmp_path / "nothing.json"
    nothing.write_text(json.dumps({"page": "y", "measured": False, "note": "the gate failed", "beats": []}), "utf8")
    assert compare.main([str(ok), str(nothing)]) == 2
    assert "measured nothing" in capsys.readouterr().out
