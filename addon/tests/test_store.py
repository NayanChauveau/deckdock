# pyright: reportAny=false, reportExplicitAny=false
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

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
    dumped = cast(list[dict[str, Any]], payload["subscriptions"])
    assert all("received" not in s for s in dumped)
    # The check state is local to this computer: never in the synced config.
    for key in ("etag", "last_checked_at", "last_error", "available_version"):
        assert all(key not in s for s in dumped)
    synced = replace(
        sub,
        received={},
        etag=None,
        last_checked_at=None,
        last_error=None,
        available_version=None,
    )
    stored = Catalog((synced, make_sub(id="s2", edition="en")))
    assert store.load_catalog(payload) == stored
    col = FakeCol()
    store.write_catalog(col, catalog)
    assert CONFIG_KEY in col.data
    assert store.read_catalog(col) == stored


def test_load_ignores_received_key_and_check_state() -> None:
    payload = _wrap(received={"g": {"fingerprint": "a", "tags": []}})
    assert store.load_catalog(payload) == Catalog((make_sub(),))
    payload = _wrap(
        etag="e", last_checked_at="T", last_error="x", available_version="2"
    )
    assert store.load_catalog(payload) == Catalog((make_sub(),))


def test_same_synced_ignores_the_check_state() -> None:
    a = Catalog((make_sub(installed_version="v1"),))
    checked = Catalog(
        (
            make_sub(
                installed_version="v1",
                etag="e",
                last_checked_at="T",
                last_error="http_error",
                available_version="v2",
            ),
        )
    )
    assert store.same_synced(a, checked)
    assert not store.same_synced(a, Catalog((make_sub(installed_version="v2"),)))
    assert not store.same_synced(a, Catalog())


def test_check_state_file_round_trip(tmp_path: Path) -> None:
    path = store.check_state_path(tmp_path)
    assert path == tmp_path / "deckdock" / "state.json"
    assert store.read_check_state(path) == {}
    one = make_sub(etag="e", last_checked_at="T", available_version="v2")
    two = make_sub(id="s2", deck_id="deck-2", last_error="not_found")
    store.write_check_state(path, Catalog((one, two)))
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]
    states = store.read_check_state(path)
    assert states == {
        "s1": store.CheckState(etag="e", last_checked_at="T", available_version="v2"),
        "s2": store.CheckState(last_error="not_found"),
    }
    # Merged into a catalog read from the config, which has no check state.
    plain = Catalog(
        (make_sub(installed_version="v1"), make_sub(id="s2", deck_id="deck-2"))
    )
    merged = store.with_check_state(plain, states)
    assert merged.subscriptions[0] == replace(one, installed_version="v1")
    assert merged.subscriptions[1] == two
    # A removed subscription leaves the file; an unknown one gets an empty state.
    store.write_check_state(path, Catalog((two,)))
    assert set(store.read_check_state(path)) == {"s2"}
    assert store.with_check_state(Catalog((make_sub(),)), {}) == Catalog((make_sub(),))


def test_check_state_file_is_tolerant(tmp_path: Path) -> None:
    path = store.check_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    for bad in ("{not json", "[1]", '{"version": 2, "subscriptions": {}}'):
        _ = path.write_text(bad, encoding="utf-8")
        assert store.read_check_state(path) == {}
    _ = path.write_text(
        json.dumps(
            {
                "version": 1,
                "subscriptions": {
                    "ok": {"etag": "e"},
                    "bad": {"etag": 3},
                    "worse": [],
                },
            }
        ),
        encoding="utf-8",
    )
    assert store.read_check_state(path) == {"ok": store.CheckState(etag="e")}


def test_catalog_with_5000_received_dumps_under_10kb() -> None:
    received = {
        f"guid-{i:05d}": Received(f"{i:016x}", ("tag-a", "tag-b")) for i in range(5000)
    }
    sub = make_sub(installed_version="v1", received=received)
    blob = json.dumps(store.dump_catalog(Catalog((sub,))), separators=(",", ":"))
    assert len(blob.encode("utf-8")) < 10_000


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


R1 = {"g1": Received("0123456789abcdef", ("t1", "é"))}
R2 = {"g1": Received("fedcba9876543210", ("t1",)), "g2": Received("1" * 16, ())}
R3 = {"g3": Received("2" * 16, ("x",))}


def test_received_path(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    assert path == tmp_path / "_deckdock_deck-1_fr.json"


def test_received_round_trip_and_file_format(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    assert store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    assert store.read_received(path, "v1", "s1") == R1
    text = path.read_text(encoding="utf-8")
    assert "é" in text and ", " not in text and ": " not in text
    assert json.loads(text) == {
        "format": "deckdock-received/1",
        "deck_id": "deck-1",
        "edition": "fr",
        "latest": "v1",
        "first_install": {"subscription": "s1", "base": None},
        "snapshots": {
            "v1": {"g1": {"fingerprint": "0123456789abcdef", "tags": ["t1", "é"]}}
        },
    }
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_received_temp_file_is_not_kept_by_check_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    seen: list[str] = []
    real = Path.replace

    def spy(self: Path, target: Path) -> Path:
        seen.append(self.name)
        return real(self, target)

    monkeypatch.setattr(Path, "replace", spy)
    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    assert len(seen) == 1 and not seen[0].startswith("_")


def test_received_keeps_the_base_snapshot(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")

    def versions() -> set[str]:
        return set(json.loads(path.read_text(encoding="utf-8"))["snapshots"])

    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    _ = store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    assert store.read_received(path, "v1", "s1") == R1
    assert store.read_received(path, "v2", "s1") == R2
    # After an undo of v2 the base is v1 again: v1 is kept, not the latest v2.
    _ = store.write_received(
        path, "deck-1", "fr", "v3", R3, subscription="s1", base="v1"
    )
    assert versions() == {"v1", "v3"}
    assert json.loads(path.read_text(encoding="utf-8"))["latest"] == "v3"
    _ = store.write_received(
        path, "deck-1", "fr", "v4", R2, subscription="s1", base="v3"
    )
    assert versions() == {"v3", "v4"}
    # Rewriting the base version itself keeps the other snapshot.
    _ = store.write_received(
        path, "deck-1", "fr", "v4", R1, subscription="s1", base="v4"
    )
    assert versions() == {"v3", "v4"}
    assert store.read_received(path, "v4", "s1") == R1
    # A base that is not in the file keeps nothing else.
    _ = store.write_received(
        path, "deck-1", "fr", "v5", R1, subscription="s1", base="gone"
    )
    assert versions() == {"v5"}


def test_received_unchanged_is_not_rewritten(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    assert store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    assert store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    before = (path.stat().st_mtime_ns, path.read_bytes())
    assert not store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before
    assert store.write_received(
        path, "deck-1", "fr", "v2", R1, subscription="s1", base="v1"
    )


def test_received_fresh_missing_and_fallback(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    assert store.read_received(path, None, "s1") == {}
    assert store.read_received(path, "v1", "s1") is None
    _ = store.write_received(path, "deck-1", "fr", "v1", {}, subscription="s1")
    assert store.read_received(path, "v1", "s1") == {}
    _ = store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    assert store.read_received(path, "v9", "s1") == R2
    assert store.read_received(path, None, "s1") == {}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["latest"] = "gone"
    _ = path.write_text(json.dumps(data), encoding="utf-8")
    assert store.read_received(path, "v9", "s1") is None
    assert store.read_received(path, "v1", "s1") == {}


def test_received_unusable_files_read_as_none(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    good = json.loads(path.read_text(encoding="utf-8"))

    def check(payload: object) -> None:
        _ = path.write_text(json.dumps(payload), encoding="utf-8")
        assert store.read_received(path, "v1", "s1") is None
        assert store.read_received(path, None, "s1") == {}

    _ = path.write_text("{not json", encoding="utf-8")
    assert store.read_received(path, "v1", "s1") is None
    _ = path.write_bytes(b"\xff\xfe")
    assert store.read_received(path, "v1", "s1") is None
    check([1])
    check({**good, "format": "deckdock-received/2"})
    check({**good, "deck_id": "other"})
    check({**good, "edition": "en"})
    check({**good, "snapshots": []})
    check({**good, "snapshots": {"v1": {"g1": {"fingerprint": 1, "tags": []}}}})
    check({**good, "snapshots": {"v1": {"g1": {"fingerprint": "a", "tags": [2]}}}})
    check({**good, "snapshots": {"v1": {"g1": {"fingerprint": "a"}}}})
    path.unlink()
    path.mkdir()
    assert store.read_received(path, "v1", "s1") is None


def test_received_fresh_subscription_finds_the_base_of_a_removed_one(
    tmp_path: Path,
) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    _ = store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    # Undoing the first install of s1 goes back to "nothing received".
    assert store.read_received(path, None, "s1") == {}
    # s1 was removed, then the same edition added again as s2: its base is back.
    assert store.read_received(path, None, "s2") == R2

    # s2 installs v3 from that base; undoing the install finds that base again.
    _ = store.write_received(path, "deck-1", "fr", "v3", R3, subscription="s2")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["first_install"] == {"subscription": "s2", "base": "v2"}
    assert set(data["snapshots"]) == {"v2", "v3"}
    assert store.read_received(path, None, "s2") == R2
    assert store.read_received(path, "v3", "s2") == R3
    # Installing again after that undo keeps the same first install.
    _ = store.write_received(path, "deck-1", "fr", "v3", R1, subscription="s2")
    assert store.read_received(path, None, "s2") == R2
    # A later update keeps the first install record.
    _ = store.write_received(
        path, "deck-1", "fr", "v4", R1, subscription="s2", base="v3"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["first_install"] == {"subscription": "s2", "base": "v2"}
    assert set(data["snapshots"]) == {"v3", "v4"}
    # Its base snapshot is gone: an undone install then starts from nothing.
    assert store.read_received(path, None, "s2") == {}
    assert store.read_received(path, None, "s3") == R1


def test_received_file_with_a_bad_first_install_is_unusable(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    good = json.loads(path.read_text(encoding="utf-8"))
    bads: list[object] = [[], {"subscription": 1, "base": None}, {"subscription": "s"}]
    for bad in bads:
        _ = path.write_text(json.dumps({**good, "first_install": bad}), "utf-8")
        assert store.read_received(path, "v1", "s1") is None
        assert store.read_received(path, None, "s2") == {}


def test_read_latest_received(tmp_path: Path) -> None:
    path = store.received_path(tmp_path, "deck-1", "fr")
    assert store.read_latest_received(path) == {}
    _ = store.write_received(path, "deck-1", "fr", "v1", R1, subscription="s1")
    _ = store.write_received(
        path, "deck-1", "fr", "v2", R2, subscription="s1", base="v1"
    )
    assert store.read_latest_received(path) == R2
    _ = path.write_text("{broken", encoding="utf-8")
    assert store.read_latest_received(path) == {}
