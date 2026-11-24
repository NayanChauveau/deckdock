"""Subscriptions, received-note fingerprints and local full versions.

The catalog is a versioned JSON object kept in the Anki collection config (so it
syncs through AnkiWeb). Only `read_catalog` / `write_catalog` touch the
collection, through a duck-typed object; this module imports neither `anki` nor
`aqt`.

The check state (ETag, last check, last error, version seen on the server)
changes at every check: it stays local to this computer, in
`<profile>/deckdock/state.json`, so the synced catalog changes only when a
subscription is added, removed or applied.

The received fingerprints are too big for the collection config: they live in a
`_deckdock_<deck_id>_<edition>.json` file of the media folder (see
`received_path`), which AnkiWeb
media sync copies to the other computers and Anki's "Check Media" keeps (its
name starts with `_`). The file holds one snapshot per installed version, so an
undo that restores the previous `installed_version` also finds its snapshot.
"""

# ruff: noqa: TRY004
# Invalid persisted data is reported as ValueError by contract (not TypeError).

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, fields
from dataclasses import replace as _with
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

CONFIG_KEY = "deckdock"
SCHEMA_VERSION = 1
RECEIVED_FORMAT = "deckdock-received/1"


class DuplicateSubscription(ValueError):
    """The same (deck_id, edition) is already subscribed."""


class ConflictingEdition(ValueError):
    """The same deck_id is already subscribed under another edition.

    The add-on cannot know before downloading whether GUIDs overlap, so any other
    edition of a followed deck is refused; the user should replace the existing
    subscription instead.
    """


class ConfigCollection(Protocol):
    def get_config(self, key: str, default: object = None, /) -> object: ...
    def set_config(self, key: str, value: object, /) -> object: ...


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
    # The check state (`CHECK_FIELDS`) is local to this computer: it is kept in
    # `<profile>/deckdock/state.json` (`read_check_state` / `write_check_state`),
    # never in the synced collection config, so a routine check never rewrites
    # the catalog that config sync merges as a whole.
    etag: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    available_version: str | None = None
    root_deck_anki_id: int | None = None
    notetype_ids: dict[str, int] = field(default_factory=dict[str, int])
    media: dict[str, MediaRecord] = field(default_factory=dict[str, MediaRecord])
    # Kept in the media folder (`read_received` / `write_received`), never in the
    # collection config.
    received: dict[str, Received] = field(default_factory=dict[str, Received])


@dataclass(frozen=True)
class Catalog:
    subscriptions: tuple[Subscription, ...] = ()


@dataclass(frozen=True)
class CheckState:
    """What the last check of a subscription found, on this computer.

    `available_version` is the version last seen on the server, which may be
    the installed one.
    """

    etag: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    available_version: str | None = None


_REQUIRED = ("id", "source_url", "base_url", "deck_id", "edition", "name")
_KNOWN = {f.name for f in fields(Subscription)}
CHECK_FIELDS = tuple(f.name for f in fields(CheckState))
_NOT_IN_CONFIG = frozenset({"received", *CHECK_FIELDS})


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
        elif f.name in _NOT_IN_CONFIG:
            continue
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
    for key in _NOT_IN_CONFIG:
        _ = raw.pop(key, None)
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
        root_deck_anki_id=root,
        notetype_ids=_load_notetype_ids(raw.get("notetype_ids", {})),
        media=_load_media(raw.get("media", {})),
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
    for k, v in _obj(raw, "received").items():
        rec = _obj(v, "received")
        if set(rec) != {"fingerprint", "tags"}:
            raise ValueError("received")
        fp = rec["fingerprint"]
        tags = _seq(rec["tags"], "received")
        if not isinstance(fp, str) or not all(isinstance(t, str) for t in tags):
            raise ValueError("received")
        out[k] = Received(fp, tuple(cast(list[str], tags)))
    return out


def _dump_received(received: dict[str, Received]) -> dict[str, object]:
    return {
        k: {"fingerprint": r.fingerprint, "tags": list(r.tags)}
        for k, r in received.items()
    }


def same_synced(a: Catalog, b: Catalog) -> bool:
    """Whether two catalogs store the same collection config (check state aside)."""
    return dump_catalog(a) == dump_catalog(b)


# --- check state (local to this computer) ---

CHECK_STATE_VERSION = 1


def check_state_path(profile_dir: Path) -> Path:
    return profile_dir / "deckdock" / "state.json"


def check_state(s: Subscription) -> CheckState:
    return CheckState(s.etag, s.last_checked_at, s.last_error, s.available_version)


def with_check_state(c: Catalog, states: dict[str, CheckState]) -> Catalog:
    """The catalog with each subscription's local check state (empty if unknown)."""
    out: list[Subscription] = []
    for s in c.subscriptions:
        state = states.get(s.id, CheckState())
        out.append(
            _with(
                s,
                etag=state.etag,
                last_checked_at=state.last_checked_at,
                last_error=state.last_error,
                available_version=state.available_version,
            )
        )
    return Catalog(tuple(out))


def _load_check_state(entry: object) -> CheckState:
    values = _obj(entry, "state")
    if set(values) - set(CHECK_FIELDS):
        raise ValueError("state")
    return CheckState(
        etag=_opt_str(values.get("etag")),
        last_checked_at=_opt_str(values.get("last_checked_at")),
        last_error=_opt_str(values.get("last_error")),
        available_version=_opt_str(values.get("available_version")),
    )


def read_check_state(path: Path) -> dict[str, CheckState]:
    """The check state by subscription id; `{}` when the file is unusable.

    An entry that is not valid is dropped: it is only a cache of the last check.
    """
    try:
        raw = _obj(cast(object, json.loads(path.read_text(encoding="utf-8"))), "state")
        if raw.get("version") != CHECK_STATE_VERSION:
            return {}
        subs = _obj(raw.get("subscriptions"), "state")
    except (OSError, ValueError, RecursionError):
        return {}
    out: dict[str, CheckState] = {}
    for sub_id, entry in subs.items():
        try:
            out[sub_id] = _load_check_state(entry)
        except ValueError:
            continue
    return out


def write_check_state(path: Path, c: Catalog) -> None:
    """Write the check state of the catalog's subscriptions atomically."""
    subs: dict[str, dict[str, str]] = {}
    for s in c.subscriptions:
        state = check_state(s)
        pairs = (
            ("etag", state.etag),
            ("last_checked_at", state.last_checked_at),
            ("last_error", state.last_error),
            ("available_version", state.available_version),
        )
        subs[s.id] = {k: v for k, v in pairs if v is not None}
    _atomic_write_json(path, {"version": CHECK_STATE_VERSION, "subscriptions": subs})


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
    _atomic_write_json(path, versions)


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


_NAME_SAFE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-.")
MAX_MEDIA_NAME_BYTES = 120  # AnkiWeb media sync skips longer file names


def _name_part(text: str) -> str:
    """`text` with every character but lowercase ASCII letters, digits, - and .
    percent-encoded (UTF-8, uppercase hex).

    The result is a valid file name part on every system, keeps "_" free for
    the separator, and two different texts never differ only by case.
    """
    return "".join(
        c if c in _NAME_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8"))
        for c in text
    )


def received_path(media_dir: Path, deck_id: str, edition: str) -> Path:
    """`_deckdock_<deck_id>_<edition>.json`, its parts encoded by `_name_part`.

    A name longer than `MAX_MEDIA_NAME_BYTES` would never reach the other
    computers: it is replaced by a hash of both parts.
    """
    name = f"_deckdock_{_name_part(deck_id)}_{_name_part(edition)}.json"
    if len(name.encode("utf-8")) > MAX_MEDIA_NAME_BYTES:
        key = json.dumps([deck_id, edition], ensure_ascii=False).encode("utf-8")
        name = f"_deckdock_{hashlib.sha256(key).hexdigest()[:40]}.json"
    return media_dir / name


def _load_first_install(raw: object) -> dict[str, str | None] | None:
    if raw is None:
        return None
    top = _obj(raw, "received")
    sub, base = top.get("subscription"), top.get("base")
    if set(top) != {"subscription", "base"} or not isinstance(sub, str):
        raise ValueError("received")
    if base is not None and not isinstance(base, str):
        raise ValueError("received")
    return {"subscription": sub, "base": base}


def _read_received_file(path: Path) -> dict[str, object] | None:
    """The validated content of a received file, or None.

    A file whose `deck_id` / `edition` would not give its own name is rejected.
    """
    try:
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
        top = _obj(raw, "received")
        deck_id, edition = top.get("deck_id"), top.get("edition")
        if (
            top.get("format") != RECEIVED_FORMAT
            or not isinstance(deck_id, str)
            or not isinstance(edition, str)
            or received_path(path.parent, deck_id, edition) != path
        ):
            return None
        snapshots = _obj(top.get("snapshots"), "received")
        top["snapshots"] = {v: _load_received(r) for v, r in snapshots.items()}
        top["first_install"] = _load_first_install(top.get("first_install"))
    except (OSError, ValueError, RecursionError):
        return None
    return top


def _latest_snapshot(top: dict[str, object]) -> dict[str, Received] | None:
    snapshots = cast(dict[str, dict[str, Received]], top["snapshots"])
    latest = top.get("latest")
    return (
        snapshots[latest] if isinstance(latest, str) and latest in snapshots else None
    )


def read_received(
    path: Path, installed_version: str | None, subscription_id: str
) -> dict[str, Received] | None:
    """The snapshot of `installed_version`, else the latest one.

    A subscription not installed yet (`installed_version` None) never gets None:
    - with no usable file, it has received nothing: `{}`;
    - when the file records that this subscription made the first install (an
      undone install), the snapshot that install started from, else `{}`;
    - otherwise (the same edition removed, then added again) the latest
      snapshot, so notes the user deleted are not created again.

    For an installed subscription, None means the file is unusable: missing,
    unreadable, malformed, written for another deck or edition than its name
    says, or without the installed snapshot nor a latest one. Never raises.
    """
    top = _read_received_file(path)
    if top is None:
        return {} if installed_version is None else None
    snapshots = cast(dict[str, dict[str, Received]], top["snapshots"])
    if installed_version is None:
        first = cast(dict[str, str | None] | None, top["first_install"])
        if first is not None and first["subscription"] == subscription_id:
            start = first["base"]
            return snapshots[start] if start is not None and start in snapshots else {}
        return _latest_snapshot(top) or {}
    if installed_version in snapshots:
        return snapshots[installed_version]
    return _latest_snapshot(top)


def read_latest_received(path: Path) -> dict[str, Received]:
    """The latest snapshot of the received file, or `{}` when it is unusable."""
    top = _read_received_file(path)
    return {} if top is None else _latest_snapshot(top) or {}


def write_received(
    path: Path,
    deck_id: str,
    edition: str,
    version: str,
    received: dict[str, Received],
    *,
    subscription: str,
    base: str | None = None,
) -> bool:
    """Write the snapshot of `version` atomically, unless the file already holds it.

    `base` is the version installed before this one. Its snapshot is kept next
    to `version` (at most two snapshots), so undoing the update finds its base
    again even after an earlier undo. When `base` is `version` itself, the other
    snapshot is kept.

    `base` None is a first install by `subscription`. The file then records it
    (`first_install`) with the latest snapshot the install started from (left
    by a removed subscription of the same edition), and keeps that snapshot as
    the base. Returns whether the file was written.
    """
    old: dict[str, dict[str, Received]] = {}
    old_first: dict[str, str | None] | None = None
    top = _read_received_file(path)
    if top is not None and received_path(path.parent, deck_id, edition) == path:
        old = cast(dict[str, dict[str, Received]], top["snapshots"])
        old_first = cast(dict[str, str | None] | None, top["first_install"])
    first = old_first
    keep_version = base
    if base is None:
        if old_first is None or old_first["subscription"] != subscription:
            latest = top.get("latest") if top is not None else None
            start = latest if isinstance(latest, str) and latest in old else None
            first = {"subscription": subscription, "base": start}
        keep_version = cast(dict[str, str | None], first)["base"]
    keep = (
        keep_version
        if keep_version != version
        else next((v for v in old if v != version), None)
    )
    snapshots = {keep: old[keep]} if keep is not None and keep in old else {}
    snapshots[version] = received
    if (
        top is not None
        and top.get("latest") == version
        and old == snapshots
        and old_first == first
    ):
        return False
    payload: dict[str, object] = {
        "format": RECEIVED_FORMAT,
        "deck_id": deck_id,
        "edition": edition,
        "latest": version,
    }
    if first is not None:
        payload["first_install"] = first
    payload["snapshots"] = {v: _dump_received(r) for v, r in snapshots.items()}
    _atomic_write_json(path, payload, separators=(",", ":"))
    return True


def _atomic_write_json(
    path: Path, payload: object, *, separators: tuple[str, str] | None = None
) -> None:
    """Write JSON through a temp file of the same folder, then replace.

    The temp name does not start with `_`, so Anki's "Check Media" reports a
    leftover one as unused instead of keeping it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="deckdock-tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=separators)
        _ = Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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
