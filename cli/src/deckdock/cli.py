"""Command-line entry point."""

import argparse
from typing import cast

from deckdock import __version__

COMMANDS = ("init", "validate", "build", "check")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckdock")
    _ = parser.add_argument("--version", action="store_true", help="show version and exit")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name in COMMANDS:
        # Stubs: filled in by later tasks.
        _ = subparsers.add_parser(name, help=f"{name} (not implemented yet)")
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
    return 0
