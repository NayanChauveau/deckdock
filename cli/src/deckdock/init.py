"""`deckdock init`: copy the Hello World project scaffold into a folder."""

import os
import re
import shutil
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from deckdock.format import SLUG_RE

DEFAULT_ID = "my-deck"
_PLACEHOLDER_ID = f"id: {DEFAULT_ID}\n"
# Stored without the dot so they ship as package data and stay inert in this repo.
_RENAMES = {
    "gitignore": ".gitignore",
    "editorconfig": ".editorconfig",
    "pre-commit-config.yaml": ".pre-commit-config.yaml",
    "github": ".github",
}


def slugify(name: str) -> str:
    """Normalize a folder name into a deck id (falls back to `my-deck`)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug if SLUG_RE.fullmatch(slug) else DEFAULT_ID


def init_project(target: Path, *, deck_id: str | None = None) -> None:
    """Create a Hello World project in `target` (missing folder, or empty apart from `.git`)."""
    if target.exists() and (
        not target.is_dir() or any(e.name != ".git" for e in target.iterdir())
    ):
        raise FileExistsError(f"{target}: target is not empty")
    if deck_id is None:
        deck_id = slugify(target.resolve().name)
    elif not SLUG_RE.fullmatch(deck_id):
        raise ValueError(f"invalid deck id {deck_id!r}")
    target.mkdir(parents=True, exist_ok=True)
    _copy(files("deckdock") / "scaffold", target, top_level=True, deck_id=deck_id)
    _link_claude_md(target)


def _copy(source: Traversable, dest: Path, *, top_level: bool, deck_id: str) -> None:
    for entry in sorted(source.iterdir(), key=lambda e: e.name):
        if entry.name == "__pycache__":
            continue
        name = _RENAMES.get(entry.name, entry.name) if top_level else entry.name
        path = dest / name
        if entry.is_dir():
            path.mkdir()
            _copy(entry, path, top_level=False, deck_id=deck_id)
            continue
        data = entry.read_bytes()
        if top_level and entry.name == "deckdock.yaml":
            text = data.decode("utf-8")
            assert _PLACEHOLDER_ID in text
            data = text.replace(_PLACEHOLDER_ID, f"id: {deck_id}\n", 1).encode("utf-8")
        _ = path.write_bytes(data)


def _link_claude_md(target: Path) -> None:
    link = target / "CLAUDE.md"
    try:
        os.symlink("AGENTS.md", link)
    except OSError:  # e.g. Windows without symlink rights
        _ = shutil.copyfile(target / "AGENTS.md", link)
