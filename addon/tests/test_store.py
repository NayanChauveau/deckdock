# pyright: reportAny=false, reportExplicitAny=false
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from deckdock_addon import store
from deckdock_addon.store import (
    CONFIG_KEY,
    Catalog,
    ConflictingEdition,
    DuplicateSubscription,
    MediaRecord,
    Received,
    Subscription,
)

BASE = Subscription(
    id="s1",
    source_url="https://github.com/o/r",
    base_url="https://example.com/fr/",
    deck_id="deck-1",
    edition="fr",
    name="Deck",
)


def make_sub(**overrides: Any) -> Subscription:
    return replace(BASE, **overrides)


class FakeCol:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def get_config(self, key: str, default: object = None) -> object:
        return self.data.get(key, default)

    def set_config(self, key: str, value: object) -> None:
        self.data[key] = value


def test_round_trip_with_media_and_received() -> None:
    sub = make_sub(
        installed_version="v1",
        etag='"abc"',
        last_checked_at="2026-11-24T10:00:00+00:00",
        last_error="boom",
        available_version="v2",
        root_deck_anki_id=42,
        notetype_ids={"basic": 7},
        media={"a.png": MediaRecord("f" * 64, "a_1.png")},
        received={"g1": Received("0123456789abcdef", ("t1", "t2"))},
    )
    catalog = Catalog((sub, make_sub(id="s2", edition="en")))
    payload = store.dump_catalog(catalog)
    assert payload["version"] == store.SCHEMA_VERSION
    assert json.loads(json.dumps(payload)) == payload
    assert store.load_catalog(payload) == catalog
    col = FakeCol()
    store.write_catalog(col, catalog)
    assert CONFIG_KEY in col.data
    assert store.read_catalog(col) == catalog


def test_load_none_is_empty() -> None:
    assert store.load_catalog(None) == Catalog()
    assert store.read_catalog(FakeCol()) == Catalog()


def _rejects(payload: object) -> None:
    with pytest.raises(ValueError):
        _ = store.load_catalog(payload)


def _wrap(**changes: Any) -> dict[str, Any]:
    good: dict[str, Any] = store.dump_catalog(Catalog((make_sub(),)))  # type: ignore[assignment]
    sub: dict[str, Any] = {**good["subscriptions"][0], **changes}
    return {"version": 1, "subscriptions": [sub]}


def test_load_rejects_unknown_version_and_keys() -> None:
    _rejects({**_wrap(), "version": 2})
    _rejects("nope")
    _rejects({"version": 1, "subscriptions": {}})
    _rejects(_wrap(extra=1))
    _rejects({"version": 1, "subscriptions": [{"id": "x"}]})
    _rejects(_wrap(received={"g": {"fingerprint": "a", "tags": [], "x": 1}}))
    _rejects(_wrap(media={"a": {"sha256": "a", "local_name": "b", "x": 1}}))
    _rejects(_wrap(notetype_ids={"basic": "7"}))
    _rejects(_wrap(root_deck_anki_id="1"))
    _rejects(_wrap(name=3))


def test_add_rejects_duplicate_and_other_edition_of_same_deck() -> None:
    catalog = store.add(Catalog(), make_sub())
    with pytest.raises(DuplicateSubscription):
        _ = store.add(catalog, make_sub(id="s2"))
    with pytest.raises(ConflictingEdition):
        _ = store.add(catalog, make_sub(id="s2", edition="en"))
    other = store.add(catalog, make_sub(id="s3", deck_id="deck-2"))
    assert len(other.subscriptions) == 2
    assert not issubclass(ConflictingEdition, DuplicateSubscription)


def test_replace_and_remove() -> None:
    catalog = store.add(Catalog(), make_sub())
    updated = store.replace(catalog, make_sub(installed_version="v9"))
    assert updated.subscriptions[0].installed_version == "v9"
    with pytest.raises(ValueError):
        _ = store.replace(catalog, make_sub(id="missing"))
    assert store.remove(catalog, "s1") == Catalog()
    assert store.remove(catalog, make_sub()) == Catalog()
    assert store.remove(catalog, "other") == catalog


def test_fingerprint_is_order_independent_and_pinned() -> None:
    assert store.fingerprint({"Front": "a", "Back": "b"}) == "25b89783598326d5"
    assert store.fingerprint({"Back": "b", "Front": "a"}) == store.fingerprint(
        {"Front": "a", "Back": "b"}
    )
    assert store.fingerprint({"Front": "é"}) != store.fingerprint({"Front": "e"})


def test_full_versions_atomic_and_tolerant(tmp_path: Path) -> None:
    path = store.full_versions_path(tmp_path, "s1")
    assert path == tmp_path / "deckdock" / "s1.json"
    assert store.read_full_versions(path) == {}
    versions = {"g1": {"Front": "a"}}
    store.write_full_versions(path, versions)
    assert store.read_full_versions(path) == versions
    assert [p.name for p in path.parent.iterdir()] == ["s1.json"]
    _ = path.write_text("{not json", encoding="utf-8")
    assert store.read_full_versions(path) == {}
    _ = path.write_text("[1]", encoding="utf-8")
    assert store.read_full_versions(path) == {}


def test_check_is_due() -> None:
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    assert store.check_is_due(None, now, 24)
    assert not store.check_is_due((now - timedelta(hours=23)).isoformat(), now, 24)
    assert store.check_is_due((now - timedelta(hours=24)).isoformat(), now, 24)
    assert store.check_is_due("2026-11-23T00:00:00", now, 24)
