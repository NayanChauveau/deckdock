"""User-facing error reporting in the `<path>:<line>: <message>` format."""

import sys
from dataclasses import dataclass
from typing import override


@dataclass(frozen=True)
class Issue:
    path: str
    message: str
    line: int | None = None

    @override
    def __str__(self) -> str:
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}: {self.message}"


def print_issues(issues: list[Issue]) -> int:
    """Write issues to stderr; return the process exit code (1 if any, else 0)."""
    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if issues else 0
