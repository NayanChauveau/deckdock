"""Command-line entry point."""

import argparse
import os
import sys
from pathlib import Path
from typing import cast

from deckdock import __version__
from deckdock.build.builder import build
from deckdock.format import check_dist
from deckdock.init import init_project
from deckdock.issues import print_issues
from deckdock.source.load import load_project
from deckdock.source.validate import validate_project

COMMANDS = ("init", "validate", "build", "check")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckdock")
    _ = parser.add_argument(
        "--version", action="store_true", help="show version and exit"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name in COMMANDS:
        if name in ("check", "validate", "build", "init"):
            continue
        # Stubs: filled in by later tasks.
        _ = subparsers.add_parser(name, help=f"{name} (not implemented yet)")
    init = subparsers.add_parser("init", help="create a Hello World deck project")
    _ = init.add_argument(
        "target", nargs="?", default=".", help="folder to create (default: .)"
    )
    check = subparsers.add_parser("check", help="check compiled deckdock/1 editions")
    _ = check.add_argument(
        "dist", nargs="?", default="dist", help="dist directory (default: dist)"
    )
    validate = subparsers.add_parser(
        "validate", help="validate the YAML sources of a project"
    )
    _ = validate.add_argument(
        "root", nargs="?", default=".", help="project root (default: .)"
    )
    build_cmd = subparsers.add_parser(
        "build", help="compile a project into dist/<edition>/"
    )
    _ = build_cmd.add_argument(
        "root", nargs="?", default=".", help="project root (default: .)"
    )
    _ = build_cmd.add_argument(
        "--out", default=None, help="output directory (default: ROOT/dist)"
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
    if command == "init":
        target = Path(cast(str, args.target))
        try:
            init_project(target)
        except FileExistsError:
            print(f"{target}: target is not empty", file=sys.stderr)
            return 1
        except OSError as exc:
            print(
                f"{target}: cannot create project: {exc.strerror or exc}",
                file=sys.stderr,
            )
            return 1
        print(f"Created deck project in {target}")
        return 0
    if command == "check":
        return print_issues(check_dist(Path(cast(str, args.dist))))
    if command == "validate":
        project, issues = load_project(Path(cast(str, args.root)))
        if project is not None:
            issues = validate_project(project)
        return print_issues(issues)
    if command == "build":
        root = Path(cast(str, args.root))
        out_arg = cast(str | None, args.out)
        out = Path(out_arg) if out_arg is not None else root / "dist"
        version = os.environ.get("DECKDOCK_VERSION", "dev")
        return print_issues(build(root, out, version))
    return 0
