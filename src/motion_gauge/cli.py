"""The motion-gauge command: `motion-gauge TOOL [ARGS]`.

    motion-gauge instrument [PAGE]               can this browser measure this page at all?
    motion-gauge busy PAGE --spec SPEC.json      how busy each beat is
    motion-gauge predicates PAGE --spec SPEC     do the storyboard's rules hold?
    motion-gauge compare CALM.json BUSY.json     two busy reports side by side
    motion-gauge snippet [--path]                print the paste-in browser instrument check
    motion-gauge examples DIR                    copy the example pages and specs into DIR
"""

from __future__ import annotations

import argparse
import sys

from motion_gauge import __version__

TOOLS = ("instrument", "busy", "predicates", "compare", "snippet", "examples")


def _snippet(argv: list[str]) -> int:
    from motion_gauge import instrument
    ap = argparse.ArgumentParser(prog="motion-gauge snippet", description="Print the paste-in browser instrument check.")
    ap.add_argument("--path", action="store_true", help="print the file's path instead of its contents")
    args = ap.parse_args(argv)
    print(str(instrument.SNIPPET) if args.path else instrument.snippet())
    return 0


def _examples(argv: list[str]) -> int:
    from motion_gauge import examples
    ap = argparse.ArgumentParser(prog="motion-gauge examples", description="Copy the example pages and specs into a folder.")
    ap.add_argument("folder")
    args = ap.parse_args(argv)
    for p in examples.copy_to(args.folder):
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="motion-gauge", description="Measure motion on rendered web pages.",
                                 epilog="Run `motion-gauge TOOL --help` for a tool's options.")
    ap.add_argument("--version", action="version", version=f"motion-gauge {__version__}")
    ap.add_argument("tool", choices=TOOLS)
    ap.add_argument("args", nargs=argparse.REMAINDER)
    ns = ap.parse_args(argv[:1] if argv and not argv[0].startswith("-") else argv)
    rest = argv[1:]
    if ns.tool == "snippet":
        return _snippet(rest)
    if ns.tool == "examples":
        return _examples(rest)
    import importlib
    return importlib.import_module(f"motion_gauge.{ns.tool}").main(rest)


if __name__ == "__main__":
    sys.exit(main())
