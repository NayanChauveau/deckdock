"""Business rules for a loaded project."""

import re
from collections.abc import Iterator
from urllib.parse import unquote

from deckdock.format import SLUG_RE
from deckdock.issues import Issue
from deckdock.source.load import CONFIG_FILE
from deckdock.source.models import (
    BasicContent,
    Card,
    ClozeContent,
    Content,
    McqContent,
    Project,
)

_CLOZE = re.compile(r"\{\{c\d+::.+?\}\}", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]*))")
_HTML_SRC = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def validate_project(project: Project) -> list[Issue]:
    issues = _validate_config(project)
    seen: dict[str, str] = {}
    for loaded in project.cards:
        card, path, line = loaded.card, loaded.path, loaded.line
        here = f"{path}:{line}"

        def add(message: str, *, _path: str = path, _line: int = line) -> None:
            issues.append(Issue(_path, message, _line))

        if not SLUG_RE.fullmatch(card.id):
            add(f"invalid card id {card.id!r}")
        if card.id in seen:
            add(f"duplicate card id '{card.id}' (also at {seen[card.id]})")
        else:
            seen[card.id] = here
        if card.deck and any(not seg.strip() for seg in card.deck.split("::")):
            add(f"empty segment in deck path {card.deck!r}")
        for edition in card.editions:
            if edition not in project.config.editions:
                add(f"unknown edition '{edition}'")
        if card.direct is None and not card.editions:
            add("no content for any edition")
        for edition, content in _contents(card):
            suffix = f" (edition '{edition}')" if edition else ""
            for message in _content_issues(content, project):
                add(message + suffix)
    return issues


def _contents(card: Card) -> Iterator[tuple[str | None, Content]]:
    if card.direct is not None:
        yield None, card.direct
    yield from card.editions.items()


def _validate_config(project: Project) -> list[Issue]:
    config = project.config
    issues: list[Issue] = []
    if not SLUG_RE.fullmatch(config.id):
        issues.append(Issue(CONFIG_FILE, f"invalid project id {config.id!r}"))
    for field, value in (("name", config.name), ("description", config.description)):
        if isinstance(value, dict):
            issues.extend(
                Issue(CONFIG_FILE, f"missing {field} for edition '{edition}'")
                for edition in config.editions
                if edition not in value
            )
    return issues


def _content_issues(content: Content, project: Project) -> list[str]:
    messages: list[str] = []
    if isinstance(content, ClozeContent) and not _CLOZE.search(content.text):
        messages.append("cloze text has no deletion")
    if isinstance(content, McqContent):
        correct = sum(1 for choice in content.choices if choice.correct)
        if len(content.choices) < 2 or correct != 1:
            messages.append(
                "mcq must have at least 2 choices and exactly one correct choice"
            )
    for ref in dict.fromkeys(_media_refs(content)):
        messages.extend(_media_issues(ref, project))
    return messages


def _texts(content: Content) -> list[str]:
    if isinstance(content, BasicContent):
        return [content.front, content.back]
    if isinstance(content, ClozeContent):
        return [content.text, content.extra]
    return [content.question, content.explanation, *(c.text for c in content.choices)]


def _media_refs(content: Content) -> Iterator[str]:
    """Local media references: Markdown images and HTML src attributes."""
    for text in _texts(content):
        for match in _MD_IMAGE.finditer(text):
            yield from _local(match.group(1) or match.group(2))
        for match in _HTML_SRC.finditer(text):
            yield from _local(match.group(1) or match.group(2))


def _local(ref: str | None) -> Iterator[str]:
    if ref and "://" not in ref and not ref.startswith(("data:", "//")):
        yield unquote(ref)


def _media_issues(ref: str, project: Project) -> list[str]:
    if not ref.startswith("media/") or ".." in ref.split("/"):
        return [f"media must live in media/ (got '{ref}')"]
    if not (project.root / ref).is_file():
        return [f"missing media file '{ref}'"]
    return []
