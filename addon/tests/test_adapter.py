"""Integration tests of the Anki adapter on a real temporary collection."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from anki.collection import Collection
from anki.dbproxy import DBProxy, ValueForDB
from anki.decks import DeckId
from anki.models import NotetypeId
from anki.notes import Note as AnkiNote
from anki.notes import NoteId
from deckdock.format import CompiledDeck, Note

from deckdock_addon import adapter
from deckdock_addon.adapter import (
    apply_plan,
    notetype_name,
    read_local_state,
    update_subscription,
)
from deckdock_addon.engine import DELETED_TAG, Plan, make_plan
from deckdock_addon.sources import SourceError, fetch_deck
from deckdock_addon.store import (
    Subscription,
    full_versions_path,
    read_catalog,
    read_full_versions,
)
from tests.conftest import (
    BASE_URL,
    FakeServer,
    basic_note,
    build_deck,
    clone,
    media_entry,
    png_bytes,
)

LABEL = "DeckDock: update Hello World"


def run(
    col: Collection,
    server: FakeServer,
    sub: Subscription,
    profile_dir: Path,
    *,
    confirmed: bool = False,
) -> tuple[Subscription, Plan]:
    return update_subscription(
        col,
        sub,
        transport=server,
        profile_dir=profile_dir,
        confirmed_full_sync=confirmed,
        undo_label=LABEL,
    )


def db(col: Collection) -> DBProxy:
    assert col.db is not None
    return col.db


def scalar(col: Collection, sql: str, *args: ValueForDB) -> int | None:
    value = cast(object, db(col).scalar(sql, *args))
    return None if value is None else int(cast(int, value))


def note_by_guid(col: Collection, guid: str) -> AnkiNote | None:
    nid = scalar(col, "select id from notes where guid = ?", guid)
    return None if nid is None else col.get_note(NoteId(nid))


def must_note(col: Collection, guid: str) -> AnkiNote:
    note = note_by_guid(col, guid)
    assert note is not None
    return note


def schema(col: Collection) -> int:
    return scalar(col, "select scm from col") or 0


def is_noop(plan: Plan) -> bool:
    return (
        plan.blocked is None
        and not plan.note_actions
        and not plan.skipped
        and not plan.media_to_download
        and all(a.change == "unchanged" for a in plan.notetype_actions)
    )


def test_install_creates_notetypes_deck_notes_media(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, plan = run(col, server, sub, profile_dir)

    assert plan.counts.created == 3
    assert col.note_count() == 3
    guids = set(cast(list[str], db(col).list("select guid from notes")))
    assert guids == {"hw-basic-1", "hw-reversed-1", "hw-cloze-1"}
    assert col.card_count() == 4  # reversed note has two cards

    assert set(new_sub.notetype_ids) == {"basic", "reversed", "cloze"}
    basic = col.models.get(NotetypeId(new_sub.notetype_ids["basic"]))
    assert basic is not None
    assert basic["name"] == "Hello World (en) · Basic"
    assert notetype_name(build_deck(), build_deck()["notetypes"][0]) == basic["name"]
    cloze = col.models.get(NotetypeId(new_sub.notetype_ids["cloze"]))
    assert cloze is not None and cloze["type"] == 1

    assert new_sub.root_deck_anki_id is not None
    assert col.decks.name(DeckId(new_sub.root_deck_anki_id)) == "Hello World"
    cloze_note = must_note(col, "hw-cloze-1")
    deck_names = {col.decks.name(c.did) for c in cloze_note.cards()}
    assert deck_names == {"Hello World::Vocabulary::Geography"}
    basic_note_ = must_note(col, "hw-basic-1")
    assert {col.decks.name(c.did) for c in basic_note_.cards()} == {"Hello World"}
    assert basic_note_.tags == ["hello"]

    media_path = Path(col.media.dir()) / "h.png"
    assert media_path.read_bytes() == png_bytes()
    assert new_sub.media["h.png"].local_name == "h.png"
    assert new_sub.installed_version == "1"
    assert new_sub.available_version is None
    assert set(new_sub.received) == guids
    assert new_sub.etag is not None

    versions = read_full_versions(full_versions_path(profile_dir, sub.id))
    assert versions["hw-reversed-1"] == {"Front": "cat", "Back": "chat"}
    assert set(versions) == guids

    # The subscription is persisted in the collection config within the operation.
    assert read_catalog(col).subscriptions == (new_sub,)

    # Applying the same version again changes nothing.
    again, plan2 = run(col, server, new_sub, profile_dir)
    assert is_noop(plan2)
    assert again.received == new_sub.received


def test_notetype_anki_id_is_used_and_marked_for_sync(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    deck = build_deck()
    deck["notetypes"][1]["anki_id"] = 1_700_000_000_001
    server.publish(deck)

    new_sub, _ = run(col, server, sub, profile_dir)

    assert new_sub.notetype_ids["reversed"] == 1_700_000_000_001
    nt = col.models.get(1_700_000_000_001)  # pyright: ignore[reportArgumentType]
    assert nt is not None
    assert nt["name"] == "Hello World (en) · Basic (and reversed card)"
    assert nt["usn"] == -1  # sent to AnkiWeb on the next sync
    assert must_note(col, "hw-reversed-1").mid == 1_700_000_000_001


def test_update_keeps_review_history(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    note = must_note(col, "hw-basic-1")
    card = note.cards()[0]
    card.start_timer()
    _ = col.sched.answerCard(card, 3)
    card.load()
    ivl, reps = card.ivl, card.reps
    revlog = scalar(col, "select count() from revlog where cid = ?", card.id)
    assert revlog == 1

    deck = build_deck("2")
    deck["notes"][0]["fields"]["Front"] = "Hello again"
    server.publish(deck)
    updated, plan = run(col, server, new_sub, profile_dir)

    assert plan.counts.updated == 1
    note = must_note(col, "hw-basic-1")
    assert note["Front"] == "Hello again"
    card.load()
    assert (card.ivl, card.reps) == (ivl, reps)
    assert scalar(col, "select count() from revlog where cid = ?", card.id) == 1
    assert updated.installed_version == "2"


def test_locally_modified_note_untouched(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    note = must_note(col, "hw-reversed-1")
    note["Back"] = "le chat"
    _ = col.update_note(note)

    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(deck)
    updated, plan = run(col, server, new_sub, profile_dir)

    assert [s.reason for s in plan.skipped] == ["modified_locally"]
    assert must_note(col, "hw-reversed-1")["Back"] == "le chat"
    assert updated.received["hw-reversed-1"] == new_sub.received["hw-reversed-1"]
    versions = read_full_versions(full_versions_path(profile_dir, sub.id))
    assert versions["hw-reversed-1"] == {"Front": "cat", "Back": "chat"}


def test_user_deleted_note_not_recreated(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    _ = col.remove_notes([must_note(col, "hw-cloze-1").id])

    server.publish(build_deck("2"))
    _, plan = run(col, server, new_sub, profile_dir)

    assert [s.reason for s in plan.skipped] == ["deleted_locally"]
    assert note_by_guid(col, "hw-cloze-1") is None
    assert col.note_count() == 2


def test_retired_note_tagged_not_deleted(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    del deck["notes"][1]
    server.publish(deck)

    updated, plan = run(col, server, new_sub, profile_dir)

    assert plan.counts.retired == 1
    assert col.note_count() == 3
    note = must_note(col, "hw-reversed-1")
    assert DELETED_TAG in note.tags
    assert "vocab" in note.tags
    assert len(note.cards()) == 2

    _, plan3 = run(col, server, updated, profile_dir)
    assert is_noop(plan3)


def test_changed_image_gets_new_local_name_and_references(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    blue = png_bytes(0, 0, 255)
    server.publish(build_deck("2", image=blue), blue)

    updated, plan = run(col, server, new_sub, profile_dir)

    local = updated.media["h.png"].local_name
    assert local.startswith("h-") and local.endswith(".png")
    assert updated.media["h.png"].sha256 == media_entry("h.png", blue)["sha256"]
    media_dir = Path(col.media.dir())
    assert (media_dir / local).read_bytes() == blue
    assert (media_dir / "h.png").read_bytes() == png_bytes()  # never overwritten
    assert plan.counts.updated == 1
    assert f'<img src="{local}">' in must_note(col, "hw-basic-1")["Back"]
    basic = col.models.get(NotetypeId(updated.notetype_ids["basic"]))
    assert basic is not None
    assert f'<img src="{local}">' in basic["tmpls"][0]["afmt"]

    _, plan3 = run(col, server, updated, profile_dir)
    assert is_noop(plan3)


def test_append_field_requires_confirmation_then_applies(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notetypes"][0]["fields"].append("Notes")
    deck["notetypes"][0]["templates"][0]["back"] += "{{Notes}}"
    deck["notes"][0]["fields"]["Notes"] = "a note"
    server.publish(deck)
    scm = schema(col)

    unchanged, plan = run(col, server, new_sub, profile_dir)

    assert plan.needs_full_sync_confirmation
    assert unchanged == new_sub
    assert schema(col) == scm
    basic = col.models.get(NotetypeId(new_sub.notetype_ids["basic"]))
    assert basic is not None
    assert col.models.field_names(basic) == ["Front", "Back"]

    updated, plan2 = run(col, server, new_sub, profile_dir, confirmed=True)

    assert plan2.needs_full_sync_confirmation
    assert schema(col) != scm
    basic = col.models.get(NotetypeId(new_sub.notetype_ids["basic"]))
    assert basic is not None
    assert col.models.field_names(basic) == ["Front", "Back", "Notes"]
    assert "{{Notes}}" in basic["tmpls"][0]["afmt"]
    assert must_note(col, "hw-basic-1")["Notes"] == "a note"
    assert updated.installed_version == "2"


def test_blocked_structure_change_applies_nothing(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notetypes"][2]["fields"] = ["Text"]
    deck["notes"][2]["fields"] = {"Text": "{{c1::Lyon}}"}
    deck["notes"].append(basic_note("hw-basic-2", "new", "note"))
    server.publish(deck)
    mod, count, scm = col.mod, col.note_count(), schema(col)

    returned, plan = run(col, server, new_sub, profile_dir)

    assert plan.blocked is not None
    assert returned == new_sub
    assert (col.mod, col.note_count(), schema(col)) == (mod, count, scm)


def test_whole_update_is_one_undo_step(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    deck["notes"].append(basic_note("hw-basic-2", "new", "note", "Vocabulary"))
    deck["notetypes"][1]["css"] = ".card { color: red; }"
    server.publish(deck)

    updated, plan = run(col, server, new_sub, profile_dir)
    assert (plan.counts.created, plan.counts.updated) == (1, 1)
    assert read_catalog(col).subscriptions == (updated,)
    assert col.undo_status().undo == LABEL

    _ = col.undo()

    assert col.note_count() == 3
    assert note_by_guid(col, "hw-basic-2") is None
    assert must_note(col, "hw-reversed-1")["Back"] == "chat"
    reversed_nt = col.models.get(NotetypeId(new_sub.notetype_ids["reversed"]))
    assert reversed_nt is not None
    assert reversed_nt["css"] == ".card { color: black; }"
    # The persisted subscription is rolled back with the collection.
    assert read_catalog(col).subscriptions == (new_sub,)


def test_existing_guid_from_other_source_is_conflict(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    stock = col.models.by_name("Basic")
    assert stock is not None
    manual = col.new_note(stock)
    manual.guid = "hw-basic-1"
    manual["Front"] = "mine"
    manual["Back"] = "untouched"
    _ = col.add_note(manual, DeckId(1))

    new_sub, plan = run(col, server, sub, profile_dir)

    assert [(s.guid, s.reason) for s in plan.skipped] == [
        ("hw-basic-1", "foreign_note")
    ]
    assert scalar(col, "select count() from notes where guid = 'hw-basic-1'") == 1
    kept = must_note(col, "hw-basic-1")
    assert (kept["Front"], kept["Back"], kept.mid) == ("mine", "untouched", stock["id"])
    assert "hw-basic-1" not in new_sub.received
    assert col.note_count() == 3


def test_apply_plan_rechecks_guid_before_creating(
    col: Collection, sub: Subscription
) -> None:
    deck = build_deck()
    plan = make_plan(deck, sub, read_local_state(col, deck, sub))
    stock = col.models.by_name("Basic")
    assert stock is not None
    manual = col.new_note(stock)
    manual.guid = "hw-cloze-1"
    manual["Front"] = "x"
    _ = col.add_note(manual, DeckId(1))

    new_sub, extra = apply_plan(col, deck, sub, plan, undo_label=LABEL)

    assert [(s.guid, s.reason) for s in extra] == [("hw-cloze-1", "foreign_note")]
    assert scalar(col, "select count() from notes where guid = 'hw-cloze-1'") == 1
    assert must_note(col, "hw-cloze-1").mid == stock["id"]
    assert "hw-cloze-1" not in new_sub.received
    assert col.note_count() == 3


def test_apply_plan_refuses_blocked_or_unconfirmed(
    col: Collection, sub: Subscription
) -> None:
    deck = build_deck()
    plan = make_plan(deck, sub, read_local_state(col, deck, sub))
    with pytest.raises(ValueError, match="blocked"):
        _ = apply_plan(col, deck, sub, replace(plan, blocked="no"), undo_label=LABEL)
    unconfirmed = replace(plan, needs_full_sync_confirmation=True)
    with pytest.raises(ValueError, match="confirm"):
        _ = apply_plan(col, deck, sub, unconfirmed, undo_label=LABEL)
    assert col.note_count() == 0


def test_failure_during_apply_rolls_back(
    col: Collection,
    server: FakeServer,
    sub: Subscription,
    profile_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    deck["notes"].append(basic_note("hw-basic-2", "new", "note"))
    server.publish(deck)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("disk full")

    monkeypatch.setattr(col, "update_notes", boom)
    with pytest.raises(RuntimeError):
        _ = run(col, server, new_sub, profile_dir)
    monkeypatch.undo()

    assert col.note_count() == 3
    assert note_by_guid(col, "hw-basic-2") is None
    assert read_catalog(col).subscriptions == (new_sub,)
    _, plan = run(col, server, new_sub, profile_dir)
    assert (plan.counts.created, plan.counts.updated) == (1, 1)


def test_network_failure_during_media_changes_nothing(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    blue = png_bytes(0, 0, 255)
    deck = build_deck("2", image=blue)
    deck["notes"].append(basic_note("hw-basic-2", "new", "note"))
    server.publish(deck, blue)
    server.failing.add(BASE_URL + "media/h.png")
    mod, count = col.mod, col.note_count()
    files = sorted(p.name for p in Path(col.media.dir()).iterdir())

    with pytest.raises(SourceError):
        _ = run(col, server, new_sub, profile_dir)

    assert (col.mod, col.note_count()) == (mod, count)
    assert sorted(p.name for p in Path(col.media.dir()).iterdir()) == files
    assert read_catalog(col).subscriptions == (new_sub,)

    server.failing.clear()
    updated, plan = run(col, server, new_sub, profile_dir)
    assert plan.counts.created == 1
    assert updated.media["h.png"].local_name != "h.png"


def test_root_deck_renamed_is_followed_and_deleted_is_recreated(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    root = new_sub.root_deck_anki_id
    assert root is not None
    _ = col.decks.rename(DeckId(root), "My Hello")

    deck = build_deck("2")
    deck["notes"].append(basic_note("hw-basic-2", "new", "note", "Vocabulary"))
    server.publish(deck)
    renamed_sub, _ = run(col, server, new_sub, profile_dir)

    assert renamed_sub.root_deck_anki_id == root
    added = must_note(col, "hw-basic-2")
    assert {col.decks.name(c.did) for c in added.cards()} == {"My Hello::Vocabulary"}
    assert col.decks.id_for_name("Hello World") is None

    _ = col.decks.remove([DeckId(root)])
    deck3 = clone(deck)
    deck3["deck"]["version"] = "3"
    deck3["notes"].append(basic_note("hw-basic-3", "third", "note"))
    server.publish(deck3)
    recreated_sub, plan = run(col, server, renamed_sub, profile_dir)

    new_root = recreated_sub.root_deck_anki_id
    assert new_root is not None and new_root != root
    assert col.decks.name(DeckId(new_root)) == "Hello World"
    third = must_note(col, "hw-basic-3")
    assert {c.did for c in third.cards()} == {new_root}
    assert {s.reason for s in plan.skipped} == {"deleted_locally"}


def big_deck(version: str, count: int, suffix: str) -> CompiledDeck:
    notes: list[Note] = [
        basic_note(f"big-{i}", f"question {i}{suffix}", f"answer {i}", "Part")
        for i in range(count)
    ]
    deck = build_deck(version, notes=notes)
    deck["notetypes"] = deck["notetypes"][:1]
    return deck


def test_5000_notes_install_and_update_under_30s(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    start = time.monotonic()
    server.publish(big_deck("1", 5000, ""))
    installed, plan = run(col, server, sub, profile_dir)
    assert plan.counts.created == 5000
    server.publish(big_deck("2", 5000, " (v2)"))
    _, plan2 = run(col, server, installed, profile_dir)
    elapsed = time.monotonic() - start

    assert plan2.counts.updated == 5000
    assert col.note_count() == 5000
    assert must_note(col, "big-4999")["Front"] == "question 4999 (v2)"
    assert elapsed < 30, f"took {elapsed:.1f} s"


def test_read_local_state_batches_sql(
    col: Collection,
    server: FakeServer,
    sub: Subscription,
    profile_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.publish(big_deck("1", 1200, ""))
    installed, _ = run(col, server, sub, profile_dir)
    deck = big_deck("1", 1200, "")
    calls: list[str] = []
    proxy = db(col)
    real_all = proxy.all

    def spy(sql: str, *args: ValueForDB) -> object:
        calls.append(sql)
        return real_all(sql, *args)

    monkeypatch.setattr(proxy, "all", spy)
    local = read_local_state(col, deck, installed)

    assert len(local.notes_by_guid) == 1200
    assert len([c for c in calls if "from notes" in c]) == 3  # chunks of 500


def test_refetches_deck_before_apply(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    version_a = build_deck("A")
    version_a["notes"][0]["fields"]["Front"] = "from A"
    version_b = build_deck("B")
    version_b["notes"][0]["fields"]["Front"] = "from B"
    server.queue(version_a, version_b)

    checked = fetch_deck(BASE_URL, etag=new_sub.etag, transport=server)
    assert checked is not None and checked.deck["deck"]["version"] == "A"
    updated, _ = run(col, server, new_sub, profile_dir)

    assert updated.installed_version == "B"
    assert must_note(col, "hw-basic-1")["Front"] == "from B"


def test_write_media_never_overwrites(col: Collection) -> None:
    existing = Path(col.media.dir()) / "h.png"
    _ = existing.write_bytes(b"someone else's file")
    data = png_bytes()

    media = adapter.write_media(col, [(media_entry("h.png", data), data)], {})

    local = media["h.png"].local_name
    assert local != "h.png"
    assert existing.read_bytes() == b"someone else's file"
    assert (Path(col.media.dir()) / local).read_bytes() == data
    assert media["h.png"].sha256 == media_entry("h.png", data)["sha256"]
