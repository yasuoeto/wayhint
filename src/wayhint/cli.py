"""``wayhint`` command line. Phase 1 provides ``validate`` only; daemon commands come later."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from wayhint import __version__
from wayhint.config import config_dir
from wayhint.yaml_store import load_all


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.config_dir) if args.config_dir else config_dir()
    result = load_all(root)
    for issue in result.issues:
        print(str(issue), file=sys.stderr)
    if result.issues:
        print(f"validate: {len(result.issues)} problem(s) in {root}", file=sys.stderr)
        return 1
    hints = sum(len(s.hints) for s in result.sheets)
    print(f"validate: ok ({len(result.sheets)} sheet(s), {hints} hint(s)) in {root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wayhint")
    parser.add_argument("--version", action="version", version=f"wayhint {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check config.yaml and hints/*.yaml; exit 1 on problems")
    v.add_argument("--config-dir", help="directory holding config.yaml and hints/ (default: XDG)")
    v.set_defaults(func=cmd_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
