"""The bundled example pages and specs: a calm page, a busy page, a storyboard and a stepped page."""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("calm.html", "busy.html", "storyboard.json", "steps.html", "steps.json")


def paths() -> dict[str, Path]:
    """Each example by its stem: calm, busy, storyboard, steps (the page) and steps_spec."""
    out = {}
    for name in FILES:
        stem = Path(name).stem
        key = f"{stem}_spec" if name.endswith(".json") and (HERE / f"{stem}.html").exists() else stem
        out[key] = HERE / name
    return out


def copy_to(folder) -> list[Path]:
    """Copy the examples into `folder` (made if missing) and return the new paths."""
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    return [Path(shutil.copy2(HERE / name, dest / name)) for name in FILES]
