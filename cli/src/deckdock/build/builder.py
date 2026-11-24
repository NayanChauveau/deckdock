"""Compile a loaded project into one deckdock/1 deck per edition under the output directory."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import cast

from deckdock import __version__
from deckdock.build.markdown import render
from deckdock.build.media import media_problem
from deckdock.build.notetypes import notetype_for
from deckdock.format import FORMAT, check_dist
from deckdock.guid import card_guid
from deckdock.issues import Issue
from deckdock.source.load import CONFIG_FILE, load_project
from deckdock.source.models import (
    BasicContent,
    ClozeContent,
    McqContent,
    Project,
)
from deckdock.source.validate import validate_project

JsonObject = dict[str, object]


def _localized(value: str | dict[str, str] | None, edition: str) -> str | None:
    if isinstance(value, dict):
        return value.get(edition)
    return value


def _deck_object(project: Project, edition: str, version: str) -> JsonObject:
    config = project.config
    deck: JsonObject = {"id": config.id, "edition": edition}
    deck["name"] = _localized(config.name, edition) or ""
    description = _localized(config.description, edition)
    if description is not None:
        deck["description"] = description
    deck["language"] = [edition]
    if config.license is not None:
        deck["license"] = config.license
    if config.homepage is not None:
        deck["homepage"] = config.homepage
    if config.options is not None:
        deck["options"] = config.options.model_dump(exclude_none=True)
    deck["version"] = version
    deck["generator"] = f"deckdock {__version__}"
    return deck


def _choices_html(content: McqContent, media: set[str]) -> str:
    items: list[str] = []
    for choice in content.choices:
        text, found = render(choice.text)
        media |= found
        attr = ' data-correct="1"' if choice.correct else ""
        items.append(f"<li{attr}>{text}</li>")
    return f'<ol class="dd-choices">{"".join(items)}</ol>'


def _fields(
    content: BasicContent | ClozeContent | McqContent, media: set[str]
) -> JsonObject:
    def md(text: str) -> str:
        out, found = render(text)
        media.update(found)
        return out

    if isinstance(content, BasicContent):
        return {"Front": md(content.front), "Back": md(content.back)}
    if isinstance(content, ClozeContent):
        return {"Text": md(content.text), "Extra": md(content.extra)}
    return {
        "Question": md(content.question),
        "Choices": _choices_html(content, media),
        "Explanation": md(content.explanation),
    }


def compile_edition(
    project: Project, edition: str, version: str
) -> tuple[JsonObject, set[str]]:
    """Compile one edition; return the deck and the root-relative media paths it references."""
    notetypes: dict[str, JsonObject] = {}
    notes: list[JsonObject] = []
    media: set[str] = set()
    for loaded in project.cards:
        card = loaded.card
        content = card.content_for(edition)
        if card.status == "draft" or content is None:
            continue
        if card.type not in notetypes:
            notetypes[card.type] = notetype_for(card.type, edition)
        notes.append(
            {
                "guid": card_guid(project.config.id, card.id, edition),
                "notetype": card.type,
                "deck": card.deck,
                "fields": _fields(content, media),
                "tags": list(card.tags),
            }
        )
    deck: JsonObject = {
        "format": FORMAT,
        "deck": _deck_object(project, edition, version),
        "notetypes": list(notetypes.values()),
        "notes": notes,
        "media": [],
    }
    return deck, media


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_plan(paths: set[str]) -> tuple[dict[str, str], list[Issue]]:
    """Map basename -> root-relative source path, reporting basename collisions."""
    plan: dict[str, str] = {}
    issues: list[Issue] = []
    for rel in sorted(paths):
        name = rel.rsplit("/", 1)[-1]
        if name in plan and plan[name] != rel:
            issues.append(Issue(CONFIG_FILE, f"media name collision '{name}'"))
        else:
            plan[name] = rel
    return plan, issues


def _is_clearable(out: Path, root: Path) -> bool:
    if out.resolve() == (root / "dist").resolve():
        return True
    if not out.exists():
        return True
    if not out.is_dir():
        return False
    entries = list(out.iterdir())
    return all(entry.is_dir() and (entry / "deck.json").is_file() for entry in entries)


def _clear(out: Path) -> None:
    if out.is_dir():
        shutil.rmtree(out)
    elif out.exists():
        out.unlink()
    out.mkdir(parents=True)


def _write_json(path: Path, data: JsonObject) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _ = path.write_bytes(text.encode("utf-8"))


def build(root: Path, out: Path, version: str) -> list[Issue]:
    """Validate the sources, write every edition under `out`, check the result."""
    project, issues = load_project(root)
    if project is not None:
        issues = validate_project(project)
    if project is None or issues:
        return issues
    if out.is_symlink():
        return [
            Issue(str(out), "output directory is a symbolic link; refusing to clear it")
        ]
    try:
        clearable = _is_clearable(out, root)
    except OSError as exc:
        return [Issue(str(out), f"cannot read output directory: {_os_error(exc)}")]
    if not clearable:
        return [Issue(str(out), "refusing to overwrite non-deckdock directory")]

    compiled: dict[str, tuple[JsonObject, dict[str, str]]] = {}
    guarded: set[str] = set()
    for edition in project.config.editions:
        deck, paths = compile_edition(project, edition, version)
        if not deck["notes"]:
            issues.append(Issue(CONFIG_FILE, f"edition '{edition}' has no cards"))
            continue
        for rel in sorted(paths - guarded):
            problem = media_problem(root, rel)
            if problem is not None:
                issues.append(Issue(CONFIG_FILE, problem))
        guarded |= paths
        plan, collisions = _media_plan(paths)
        issues.extend(collisions)
        compiled[edition] = (deck, plan)
    if issues:
        return issues

    try:
        _clear(out)
        _write_editions(root, out, compiled)
    except OSError as exc:
        return [Issue(str(out), f"cannot write output: {_os_error(exc)}")]
    return check_dist(out)


def _os_error(exc: OSError) -> str:
    filename = cast(object, exc.filename)
    if exc.strerror and filename is not None:
        return f"{exc.strerror}: '{filename}'"
    return exc.strerror or str(exc)


def _write_editions(
    root: Path, out: Path, compiled: dict[str, tuple[JsonObject, dict[str, str]]]
) -> None:
    for edition, (deck, plan) in compiled.items():
        media_dir = out / edition / "media"
        (out / edition).mkdir(parents=True, exist_ok=True)
        entries: list[object] = []
        for name in sorted(plan):
            source = root / plan[name]
            media_dir.mkdir(exist_ok=True)
            _ = shutil.copyfile(source, media_dir / name)
            entries.append(
                {
                    "filename": name,
                    "sha256": _sha256(source),
                    "size": source.stat().st_size,
                }
            )
        deck["media"] = entries
        _write_json(out / edition / "deck.json", deck)
