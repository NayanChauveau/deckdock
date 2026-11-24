"""Subscriptions, received-note fingerprints and local full versions.

The catalog is a versioned JSON object kept in the Anki collection config (so it
syncs through AnkiWeb). Only `read_catalog` / `write_catalog` touch the
collection, through a duck-typed object; this module imports neither `anki` nor
`aqt`.
"""

# ruff: noqa: TRY004
# Invalid persisted data is reported as ValueError by contract (not TypeError).

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

CONFIG_KEY = "deckdock"
SCHEMA_VERSION = 1


class DuplicateSubscription(ValueError):
    """The same (deck_id, edition) is already subscribed."""


class ConflictingEdition(ValueError):
    """The same deck_id is already subscribed under another edition.

    The add-on cannot know before downloading whether GUIDs overlap, so any other
    edition of a followed deck is refused; the user should replace the existing
    subscription instead.
    """


class ConfigCollection(Protocol):
    def get_config(self, key: str, default: object = None) -> object: ...
    def set_config(self, key: str, value: object) -> object: ...


@dataclass(frozen=True)
class MediaRecord:
    sha256: str
    local_name: str


@dataclass(frozen=True)
class Received:
    fingerprint: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Subscription:
    id: str
    source_url: str
    base_url: str
    deck_id: str
    edition: str
    name: str
    installed_version: str | None = None
    etag: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    available_version: str | None = None
    root_deck_anki_id: int | None = None
    notetype_ids: dict[str, int] = field(default_factory=dict[str, int])
    media: dict[str, MediaRecord] = field(default_factory=dict[str, MediaRecord])
    received: dict[str, Received] = field(default_factory=dict[str, Received])


@dataclass(frozen=True)
class Catalog:
    subscriptions: tuple[Subscription, ...] = ()


_REQUIRED = ("id", "source_url", "base_url", "deck_id", "edition", "name")
_KNOWN = {f.name for f in fields(Subscription)}


def dump_catalog(c: Catalog) -> dict[str, object]:
    return {
        "version": SCHEMA_VERSION,
        "subscriptions": [_dump_subscription(s) for s in c.subscriptions],
    }


def _dump_subscription(s: Subscription) -> dict[str, object]:
    out: dict[str, object] = {}
    for f in fields(s):
        if f.name == "media":
            out["media"] = {
                k: {"sha256": m.sha256, "local_name": m.local_name}
                for k, m in s.media.items()
            }
        elif f.name == "received":
            out["received"] = {
                k: {"fingerprint": r.fingerprint, "tags": list(r.tags)}
                for k, r in s.received.items()
            }
        elif f.name == "notetype_ids":
            out["notetype_ids"] = dict(s.notetype_ids)
        else:
            out[f.name] = getattr(s, f.name)
    return out


def load_catalog(payload: object) -> Catalog:
    if payload is None:
        return Catalog()
    top = _obj(payload, "catalog")
    if top.get("version") != SCHEMA_VERSION:
        raise ValueError("catalog_version")
    raw = _seq(top.get("subscriptions", []), "catalog")
    return Catalog(tuple(_load_subscription(item) for item in raw))


def _obj(v: object, code: str) -> dict[str, object]:
    if not isinstance(v, dict):
        raise ValueError(code)
    out: dict[str, object] = {}
    for k, val in cast(dict[object, object], v).items():
        if not isinstance(k, str):
            raise ValueError(code)
        out[k] = val
    return out


def _seq(v: object, code: str) -> list[object]:
    if not isinstance(v, list):
        raise ValueError(code)
    return list(cast(list[object], v))


def _load_subscription(item: object) -> Subscription:
    raw = _obj(item, "subscription")
    if set(raw) - _KNOWN or any(k not in raw for k in _REQUIRED):
        raise ValueError("subscription")
    req = [_req_str(raw[k]) for k in _REQUIRED]
    root = raw.get("root_deck_anki_id")
    if root is not None and (not isinstance(root, int) or isinstance(root, bool)):
        raise ValueError("subscription")
    return Subscription(
        id=req[0],
        source_url=req[1],
        base_url=req[2],
        deck_id=req[3],
        edition=req[4],
        name=req[5],
        installed_version=_opt_str(raw.get("installed_version")),
        etag=_opt_str(raw.get("etag")),
        last_checked_at=_opt_str(raw.get("last_checked_at")),
        last_error=_opt_str(raw.get("last_error")),
        available_version=_opt_str(raw.get("available_version")),
        root_deck_anki_id=root,
        notetype_ids=_load_notetype_ids(raw.get("notetype_ids", {})),
        media=_load_media(raw.get("media", {})),
        received=_load_received(raw.get("received", {})),
    )


def _req_str(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("subscription")
    return v


def _opt_str(v: object) -> str | None:
    return None if v is None else _req_str(v)


def _load_notetype_ids(raw: object) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in _obj(raw, "subscription").items():
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("subscription")
        out[k] = v
    return out


def _load_media(raw: object) -> dict[str, MediaRecord]:
    out: dict[str, MediaRecord] = {}
    for k, v in _obj(raw, "subscription").items():
        rec = _obj(v, "subscription")
        if set(rec) != {"sha256", "local_name"}:
            raise ValueError("subscription")
        out[k] = MediaRecord(_req_str(rec["sha256"]), _req_str(rec["local_name"]))
    return out


def _load_received(raw: object) -> dict[str, Received]:
    out: dict[str, Received] = {}
    for k, v in _obj(raw, "subscription").items():
        rec = _obj(v, "subscription")
        if set(rec) != {"fingerprint", "tags"}:
            raise ValueError("subscription")
        tags = tuple(_req_str(t) for t in _seq(rec["tags"], "subscription"))
        out[k] = Received(_req_str(rec["fingerprint"]), tags)
    return out


def add(c: Catalog, s: Subscription) -> Catalog:
    for existing in c.subscriptions:
        if existing.deck_id != s.deck_id:
            continue
        if existing.edition == s.edition:
            raise DuplicateSubscription(f"{s.deck_id} ({s.edition})")
        raise ConflictingEdition(
            f"{s.deck_id} is already followed as edition {existing.edition!r}; replace it instead"
        )
    return Catalog((*c.subscriptions, s))


def replace(c: Catalog, s: Subscription) -> Catalog:
    if not any(x.id == s.id for x in c.subscriptions):
        raise ValueError(f"unknown subscription {s.id}")
    return Catalog(tuple(s if x.id == s.id else x for x in c.subscriptions))


def remove(c: Catalog, target: Subscription | str) -> Catalog:
    sid = target if isinstance(target, str) else target.id
    return Catalog(tuple(x for x in c.subscriptions if x.id != sid))


def fingerprint(fields: dict[str, str]) -> str:
    blob = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def full_versions_path(profile_dir: Path, subscription_id: str) -> Path:
    return profile_dir / "deckdock" / f"{subscription_id}.json"


def write_full_versions(path: Path, versions: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(versions, fh, ensure_ascii=False)
        _ = Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_full_versions(path: Path) -> dict[str, dict[str, str]]:
    try:
        data = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for guid, flds in cast(dict[object, object], data).items():
        if not isinstance(guid, str) or not isinstance(flds, dict):
            return {}
        entry: dict[str, str] = {}
        for k, v in cast(dict[object, object], flds).items():
            if not isinstance(k, str) or not isinstance(v, str):
                return {}
            entry[k] = v
        out[guid] = entry
    return out


def read_catalog(col: ConfigCollection) -> Catalog:
    return load_catalog(col.get_config(CONFIG_KEY, None))


def write_catalog(col: ConfigCollection, c: Catalog) -> None:
    _ = col.set_config(CONFIG_KEY, dump_catalog(c))


def check_is_due(
    last_checked_at: str | None, now: datetime, interval_hours: int
) -> bool:
    if last_checked_at is None:
        return True
    checked = datetime.fromisoformat(last_checked_at)
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return now - checked >= timedelta(hours=interval_hours)
