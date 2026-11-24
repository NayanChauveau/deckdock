"""Command-line entry point."""

import argparse
from pathlib import Path
from typing import cast

from deckdock import __version__
from deckdock.format import check_dist
from deckdock.issues import print_issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckdock")
    _ = parser.add_argument(
        "--version", action="store_true", help="show version and exit"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    check = subparsers.add_parser("check", help="check compiled deckdock/1 editions")
    _ = check.add_argument(
        "dist", nargs="?", default="dist", help="dist directory (default: dist)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if cast(bool, args.version):
        print(f"deckdock {__version__}")
        return 0
    command = cast(str | None, args.command)
    if command is None:
        parser.print_help()
        return 0
    if command == "check":
        return print_issues(check_dist(Path(cast(str, args.dist))))
    return 0
