"""The motion-gauge command: one entry point for every tool, plus the snippet and the examples."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from motion_gauge import cli, instrument


def test_snippet_prints_the_paste_in_check(capsys):
    assert cli.main(["snippet"]) == 0
    assert capsys.readouterr().out.strip() == instrument.snippet().strip()


def test_snippet_path_prints_where_the_file_is(capsys):
    assert cli.main(["snippet", "--path"]) == 0
    assert capsys.readouterr().out.strip().endswith("instrument_check.js")


def test_examples_are_copied_out(tmp_path):
    assert cli.main(["examples", str(tmp_path / "ex")]) == 0
    got = sorted(p.name for p in (tmp_path / "ex").iterdir())
    assert got == ["busy.html", "calm.html", "steps.html", "steps.json", "storyboard.json"]
    json.loads((tmp_path / "ex" / "storyboard.json").read_text("utf8"))


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_an_unknown_tool_is_refused(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["sparkle"])
    assert e.value.code == 2


def test_the_installed_command_runs_the_instrument(tmp_path, healthy_clock):
    run = subprocess.run([sys.executable, "-m", "motion_gauge", "instrument", "--viewport", "800x600"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    g = json.loads(run.stdout)
    assert g["ok"] is True and g["headless"] is True
