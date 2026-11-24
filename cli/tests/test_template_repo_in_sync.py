"""The sibling `deckdock-template` repo must stay byte-identical to `deckdock init`."""

import os
from pathlib import Path

import pytest

from deckdock.init import init_project

TEMPLATE = Path(__file__).parents[3] / "deckdock-template"
_IGNORED_TOP = {".git", "dist"}


def _snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    """Relative path -> ("link", target) for symlinks, ("file", bytes) otherwise."""
    result: dict[str, tuple[str, bytes | str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if here == root:
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_TOP]
        for name in filenames:
            path = here / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[rel] = ("link", os.readlink(path))
            else:
                result[rel] = ("file", path.read_bytes())
    return result


@pytest.mark.skipif(
    not TEMPLATE.exists(), reason="template repo not checked out next to deckdock"
)
def test_template_repo_matches_init(tmp_path: Path):
    generated = tmp_path / "deckdock-template"
    init_project(generated, deck_id="my-deck")
    assert _snapshot(TEMPLATE) == _snapshot(generated)
