"""Integration tests of the Anki adapter on a real temporary collection."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from anki.collection import AddNoteRequest, Collection
from anki.dbproxy import DBProxy, ValueForDB
from anki.decks import DeckId
from anki.models import NotetypeId
from anki.notes import Note as AnkiNote
from anki.notes import NoteId
from deckdock.format import CompiledDeck, Note

from deckdock_addon import adapter
from deckdock_addon.adapter import (
    ApplyRefusedError,
    PartialApplyError,
    apply_plan,
    notetype_name,
    preview_plan,
    read_local_state,
    update_subscription,
    with_received,
)
from deckdock_addon.engine import (
    DELETED_TAG,
    RECEIVED_MISSING,
    Plan,
    make_plan,
    summary_lines,
)
from deckdock_addon.sources import SourceError, fetch_deck
from deckdock_addon.store import (
    Catalog,
    Subscription,
    full_versions_path,
    read_catalog,
    read_full_versions,
    read_received,
    received_path,
    remove,
    write_catalog,
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


def stored(col: Collection) -> tuple[Subscription, ...]:
    """The persisted subscriptions: config plus received file of the media folder."""
    out: list[Subscription] = []
    for s in read_catalog(col).subscriptions:
        loaded = with_received(col, s)
        assert loaded is not None
        out.append(loaded)
    return tuple(out)


def synced(sub: Subscription) -> Subscription:
    """`sub` as the collection config stores it: without the local check state."""
    return replace(
        sub, etag=None, last_checked_at=None, last_error=None, available_version=None
    )


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
    assert stored(col) == (synced(new_sub),)

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
    assert stored(col) == (synced(updated),)
    assert col.undo_status().undo == LABEL

    _ = col.undo()

    assert col.note_count() == 3
    assert note_by_guid(col, "hw-basic-2") is None
    assert must_note(col, "hw-reversed-1")["Back"] == "chat"
    reversed_nt = col.models.get(NotetypeId(new_sub.notetype_ids["reversed"]))
    assert reversed_nt is not None
    assert reversed_nt["css"] == ".card { color: black; }"
    # The persisted subscription is rolled back with the collection.
    assert stored(col) == (synced(new_sub),)


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
    assert stored(col) == (synced(new_sub),)
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
    assert stored(col) == (synced(new_sub),)

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


def deckdock_notetypes(col: Collection) -> list[str]:
    return sorted(
        x.name for x in col.models.all_names_and_ids() if x.name.startswith("Hello")
    )


def user_action(col: Collection) -> str:
    """Make an undoable change of the user's own; return its undo label."""
    stock = col.models.by_name("Basic")
    assert stock is not None
    note = col.new_note(stock)
    note["Front"] = "my own note"
    _ = col.add_note(note, DeckId(1))
    label = col.undo_status().undo
    assert label
    return label


def test_filtered_deck_clash_refused_before_any_write(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    label = user_action(col)
    filtered = col.decks.new_filtered("Hello World")
    label = col.undo_status().undo or label
    mod, count = col.mod, col.note_count()

    with pytest.raises(ApplyRefusedError) as raised:
        _ = run(col, server, sub, profile_dir)

    assert raised.value.code == "deck_name_conflict"
    assert deckdock_notetypes(col) == []
    assert (col.mod, col.note_count()) == (mod, count)
    assert col.undo_status().undo == label
    assert stored(col) == ()

    _ = col.decks.rename(filtered, "My filtered deck")
    new_sub, plan = run(col, server, sub, profile_dir)
    assert plan.counts.created == 3
    assert new_sub.root_deck_anki_id != filtered


def test_subdeck_under_filtered_deck_refused(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    _ = col.decks.new_filtered("Hello World::Extra")
    deck = build_deck("2")
    deck["notes"].append(basic_note("hw-basic-2", "new", "note", "Extra::More"))
    server.publish(deck)
    count = col.note_count()

    with pytest.raises(ApplyRefusedError, match="filtered"):
        _ = run(col, server, new_sub, profile_dir)
    assert col.note_count() == count
    assert stored(col) == (synced(new_sub),)


def test_note_deleted_between_plan_and_apply_is_refused(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    deck["notes"].append(basic_note("hw-basic-2", "new", "note"))
    plan = make_plan(deck, new_sub, read_local_state(col, deck, new_sub))
    _ = col.remove_notes([must_note(col, "hw-reversed-1").id])
    count = col.note_count()
    label = col.undo_status().undo

    with pytest.raises(ApplyRefusedError) as raised:
        _ = apply_plan(col, deck, new_sub, plan, undo_label=LABEL)

    assert raised.value.code == "collection_changed"
    assert col.note_count() == count
    assert note_by_guid(col, "hw-basic-2") is None
    assert col.undo_status().undo == label


def test_backend_error_mid_apply_is_reported_and_retry_does_not_duplicate(
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
    real_update = col.update_notes

    def update_with_missing_note(notes: list[AnkiNote]) -> object:
        ghost = col.get_note(notes[0].id)
        ghost.id = NoteId(999_999_999)  # the backend fails: no such note
        return real_update([*notes, ghost])

    monkeypatch.setattr(col, "update_notes", update_with_missing_note)
    with pytest.raises(PartialApplyError) as raised:
        _ = run(col, server, new_sub, profile_dir)
    monkeypatch.undo()

    assert raised.value.__cause__ is not None
    assert "Check again" in str(raised.value)
    assert stored(col) == (synced(new_sub),)

    finished, plan = run(col, server, new_sub, profile_dir)

    assert finished.installed_version == "2"
    assert deckdock_notetypes(col) == [
        "Hello World (en) · Basic",
        "Hello World (en) · Basic (and reversed card)",
        "Hello World (en) · Cloze",
    ]
    assert col.note_count() == 4
    assert scalar(col, "select count() from notes where guid = 'hw-basic-2'") == 1
    assert must_note(col, "hw-reversed-1")["Back"] == "chatte"
    assert "hw-basic-2" in finished.received
    assert not plan.skipped
    _, plan3 = run(col, server, finished, profile_dir)
    assert is_noop(plan3)


def test_partial_install_retry_reuses_notetypes_and_root_deck(
    col: Collection,
    server: FakeServer,
    sub: Subscription,
    profile_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_add = col.add_notes

    def add_with_broken_note(requests: list[AddNoteRequest]) -> object:
        broken = col.new_note(requests[0].note.note_type() or {})
        broken.mid = NotetypeId(999_999_999)  # the backend fails: no such notetype
        return real_add([*requests, AddNoteRequest(broken, requests[0].deck_id)])

    monkeypatch.setattr(col, "add_notes", add_with_broken_note)
    with pytest.raises(PartialApplyError) as raised:
        _ = run(col, server, sub, profile_dir)
    monkeypatch.undo()

    assert raised.value.__cause__ is not None
    assert col.note_count() == 0
    assert len(deckdock_notetypes(col)) == 3  # left by the failed attempt
    assert stored(col) == ()

    new_sub, plan = run(col, server, sub, profile_dir)

    assert plan.counts.created == 3
    assert len(deckdock_notetypes(col)) == 3
    assert [d.name for d in col.decks.all_names_and_ids()].count("Hello World") == 1
    assert col.note_count() == 3
    _, plan2 = run(col, server, new_sub, profile_dir)
    assert is_noop(plan2)


def test_user_edit_during_media_download_is_not_overwritten(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    blue = png_bytes(0, 0, 255)
    deck = build_deck("2", image=blue)
    deck["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(deck, blue)

    def user_edits(_name: str) -> None:
        note = must_note(col, "hw-reversed-1")
        note["Back"] = "my own translation"
        _ = col.update_note(note)

    server.on_media = user_edits
    updated, plan = run(col, server, new_sub, profile_dir)

    assert must_note(col, "hw-reversed-1")["Back"] == "my own translation"
    assert [(s.guid, s.reason) for s in plan.skipped] == [
        ("hw-reversed-1", "modified_locally")
    ]
    assert updated.media["h.png"].local_name != "h.png"
    assert plan.counts.updated == 1  # the basic note, for its new image name


def test_noop_update_adds_no_undo_entry(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    label = user_action(col)

    again, plan = run(col, server, new_sub, profile_dir)

    assert is_noop(plan)
    assert col.undo_status().undo == label
    assert again.etag != new_sub.etag  # the fake server sends a new ETag each time
    assert stored(col) == (synced(again),)
    assert col.note_count() == 4


def other_deck(version: str = "1") -> CompiledDeck:
    """A different deck with the same display name, edition and structure."""
    deck = build_deck(version)
    deck["deck"]["id"] = "other-deck"
    deck["notetypes"][0]["templates"][0]["front"] = "OTHER {{Front}}"
    deck["notetypes"][0]["css"] = ".other {}"
    deck["notes"] = [basic_note("other-1", "other", "deck")]
    return deck


def other_sub() -> Subscription:
    return Subscription(
        id="sub-2",
        source_url=BASE_URL,
        base_url=BASE_URL,
        deck_id="other-deck",
        edition="en",
        name="Hello World",
    )


def test_two_decks_same_display_name_get_separate_notetypes(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    sub_a, _ = run(col, server, sub, profile_dir)
    basic_a = col.models.get(NotetypeId(sub_a.notetype_ids["basic"]))
    assert basic_a is not None
    assert basic_a["deckdock"] == {
        "deck_id": "hello-world",
        "edition": "en",
        "slug": "basic",
    }
    before = (basic_a["tmpls"][0]["qfmt"], basic_a["css"])

    server_b = FakeServer()
    server_b.publish(other_deck(), png_bytes())
    sub_b, plan_b = run(col, server_b, other_sub(), profile_dir)
    deck_b2 = other_deck("2")
    deck_b2["notetypes"][0]["css"] = ".other { color: red; }"
    server_b.publish(deck_b2)
    sub_b, _ = run(col, server_b, sub_b, profile_dir)

    assert plan_b.counts.created == 1
    assert not set(sub_a.notetype_ids.values()) & set(sub_b.notetype_ids.values())
    basic_a = col.models.get(NotetypeId(sub_a.notetype_ids["basic"]))
    assert basic_a is not None
    assert (basic_a["tmpls"][0]["qfmt"], basic_a["css"]) == before
    assert must_note(col, "other-1").mid == sub_b.notetype_ids["basic"]
    catalog_a = next(s for s in stored(col) if s.id == sub.id)
    _, plan_a = run(col, server, catalog_a, profile_dir)
    assert is_noop(plan_a)


def test_user_notetype_with_same_name_not_adopted(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    mm = col.models
    mine = mm.new("Hello World (en) · Basic")
    for name in ("Front", "Back"):
        mm.add_field(mine, mm.new_field(name))
    template = mm.new_template("Card 1")
    template["qfmt"] = "MY {{Front}}"
    template["afmt"] = "MY {{Back}}"
    mm.add_template(mine, template)
    mine_id = int(mm.add(mine).id)

    new_sub, _ = run(col, server, sub, profile_dir)

    assert new_sub.notetype_ids["basic"] != mine_id
    kept = mm.get(NotetypeId(mine_id))
    assert kept is not None
    assert kept["tmpls"][0]["qfmt"] == "MY {{Front}}"
    assert must_note(col, "hw-basic-1").mid == new_sub.notetype_ids["basic"]


def test_anki_id_mapped_by_other_subscription_not_reused(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    deck_a = build_deck()
    deck_a["notetypes"][0]["anki_id"] = 1_700_000_000_002
    server.publish(deck_a)
    sub_a, _ = run(col, server, sub, profile_dir)
    assert sub_a.notetype_ids["basic"] == 1_700_000_000_002

    deck_b = other_deck()
    deck_b["notetypes"][0]["anki_id"] = 1_700_000_000_002
    server_b = FakeServer()
    server_b.publish(deck_b, png_bytes())
    sub_b, _ = run(col, server_b, other_sub(), profile_dir)

    assert sub_b.notetype_ids["basic"] != 1_700_000_000_002
    basic_a = col.models.get(NotetypeId(1_700_000_000_002))
    assert basic_a is not None
    assert basic_a["tmpls"][0]["qfmt"] == "{{Front}}"
    assert must_note(col, "other-1").mid == sub_b.notetype_ids["basic"]


def test_preview_plan_matches_the_update_and_writes_nothing(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    fetched = fetch_deck(BASE_URL, etag=None, transport=server)
    assert fetched is not None
    before = col.note_count()

    preview = adapter.preview_plan(col, fetched.deck, sub)

    assert col.note_count() == before == 0
    assert not col.undo_status().undo
    _, applied = run(col, server, sub, profile_dir)
    assert preview == applied


def received_file(col: Collection) -> Path:
    return received_path(Path(col.media.dir()), "hello-world", "en")


def test_received_kept_in_media_folder_not_in_config(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)

    path = received_file(col)
    assert path.parent == Path(col.media.dir())
    assert path.name == "_deckdock_hello-world_en.json"
    assert read_received(path, "1", sub.id) == new_sub.received
    assert len(new_sub.received) == 3
    (stored_sub,) = read_catalog(col).subscriptions
    assert stored_sub.received == {}
    assert "received" not in str(cast(object, col.get_config("deckdock")))
    # Anki's media check keeps the file.
    report = col.media.check()
    assert path.name not in report.unused
    assert path.exists()


def test_noop_update_does_not_rewrite_received_file(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    new_sub, _ = run(col, server, sub, profile_dir)
    path = received_file(col)
    before = (path.stat().st_mtime_ns, path.read_bytes())
    time.sleep(0.01)

    _, plan = run(col, server, new_sub, profile_dir)

    assert is_noop(plan)
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


def test_undo_uses_the_previous_received_snapshot(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    _ = run(col, server, sub, profile_dir)
    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(deck)
    (installed,) = read_catalog(col).subscriptions
    _, plan = run(col, server, installed, profile_dir)
    assert plan.counts.updated == 1
    assert read_received(received_file(col), "2", "sub-1") != read_received(
        received_file(col), "1", "sub-1"
    )

    _ = col.undo()

    (current,) = read_catalog(col).subscriptions
    assert current.installed_version == "1"
    assert must_note(col, "hw-reversed-1")["Back"] == "chat"
    again = preview_plan(col, deck, current)
    assert [a.guid for a in again.note_actions] == ["hw-reversed-1"]
    assert all(s.reason != "modified_locally" for s in again.skipped)
    updated, applied = run(col, server, current, profile_dir)
    assert applied.counts.updated == 1
    assert must_note(col, "hw-reversed-1")["Back"] == "chatte"
    assert updated.installed_version == "2"


def test_received_write_failure_keeps_the_update(
    col: Collection,
    server: FakeServer,
    sub: Subscription,
    profile_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(adapter, "write_received", fail)

    new_sub, plan = run(col, server, sub, profile_dir)

    assert plan.counts.created == 3
    assert col.note_count() == 3
    assert new_sub.installed_version == "1"
    assert not received_file(col).exists()
    assert "disk full" in caplog.text


def test_missing_received_file_blocks_the_plan(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    _ = run(col, server, sub, profile_dir)
    _ = col.remove_notes([must_note(col, "hw-cloze-1").id])
    received_file(col).unlink()  # the config synced, the media not yet
    deck = build_deck("2")
    deck["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(deck)
    (installed,) = read_catalog(col).subscriptions
    assert installed.installed_version == "1"
    mod, count = col.mod, col.note_count()

    plan = preview_plan(col, deck, installed)
    assert plan.blocked is not None
    assert plan.blocked_code == RECEIVED_MISSING
    assert not plan.note_actions
    returned, held = run(col, server, installed, profile_dir)

    assert held.blocked_code == RECEIVED_MISSING
    assert returned == installed
    assert (col.mod, col.note_count()) == (mod, count)
    assert note_by_guid(col, "hw-cloze-1") is None
    assert must_note(col, "hw-reversed-1")["Back"] == "chat"
    assert not received_file(col).exists()
    fr = (
        "Hello World (en) — Les données de suivi de ce deck ne sont pas encore "
        "arrivées sur cet ordinateur. Synchronise Anki (médias compris), puis "
        "réessaie."
    )
    en = (
        "Hello World (en) — This deck's tracking data has not reached this "
        "computer yet. Sync Anki (including media), then try again."
    )
    assert summary_lines(held, "Hello World", "en", "fr") == [fr]
    assert summary_lines(held, "Hello World", "en", "en") == [en]


def test_double_undo_keeps_the_base_snapshot(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    _ = run(col, server, sub, profile_dir)
    v2 = build_deck("2")
    v2["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(v2)
    (installed,) = read_catalog(col).subscriptions
    _ = run(col, server, installed, profile_dir)
    _ = col.undo()

    v3 = build_deck("3")
    v3["notes"][1]["fields"]["Back"] = "minou"
    v3["notes"].append(basic_note("hw-basic-3", "three", "3"))
    server.publish(v3)
    (current,) = read_catalog(col).subscriptions
    assert current.installed_version == "1"
    _, applied = run(col, server, current, profile_dir)
    assert (applied.counts.created, applied.counts.updated) == (1, 1)
    _ = col.undo()

    (current,) = read_catalog(col).subscriptions
    assert current.installed_version == "1"
    assert note_by_guid(col, "hw-basic-3") is None
    again = preview_plan(col, v3, current)
    assert again.skipped == ()
    assert (again.counts.created, again.counts.updated) == (1, 1)
    _ = run(col, server, current, profile_dir)
    assert must_note(col, "hw-reversed-1")["Back"] == "minou"
    assert must_note(col, "hw-basic-3")["Front"] == "three"


def test_browser_search_finds_the_skipped_notes(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    _ = run(col, server, sub, profile_dir)
    guids = ["hw-basic-1", "hw-cloze-1", "absent-guid"]

    search = adapter.browser_search(col, guids)

    assert search is not None
    found = set(col.find_notes(search))
    assert found == {must_note(col, "hw-basic-1").id, must_note(col, "hw-cloze-1").id}
    assert adapter.browser_search(col, ["absent-guid"]) is None
    assert adapter.browser_search(col, []) is None


def test_readding_the_same_edition_finds_its_base(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    _ = run(col, server, sub, profile_dir)
    _ = col.remove_notes([must_note(col, "hw-cloze-1").id])
    edited = must_note(col, "hw-reversed-1")
    edited["Back"] = "my own translation"
    _ = col.update_note(edited)
    write_catalog(col, remove(read_catalog(col), sub.id))
    again = replace(sub, id="sub-2")

    preview = preview_plan(col, build_deck(), again)
    _, plan = run(col, server, again, profile_dir)

    assert preview == plan
    assert note_by_guid(col, "hw-cloze-1") is None
    assert must_note(col, "hw-reversed-1")["Back"] == "my own translation"
    assert sorted((s.guid, s.reason) for s in plan.skipped) == [
        ("hw-cloze-1", "deleted_locally"),
        ("hw-reversed-1", "modified_locally"),
    ]
    assert plan.counts.created == 0
    assert col.note_count() == 2


def test_undoing_the_first_install_lets_it_be_installed_again(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    write_catalog(col, Catalog((sub,)))  # added before the install, like the UI
    _ = run(col, server, sub, profile_dir)
    _ = col.undo()
    (current,) = read_catalog(col).subscriptions
    assert current.installed_version is None
    assert col.note_count() == 0

    _, plan = run(col, server, current, profile_dir)

    assert plan.counts.created == 3
    assert plan.skipped == ()
    assert col.note_count() == 3


def test_catalog_rolled_back_by_sync_still_updates_notes(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    v1_sub, _ = run(col, server, sub, profile_dir)
    v2 = build_deck("2")
    v2["notes"][1]["fields"]["Back"] = "chatte"
    server.publish(v2)
    _ = run(col, server, v1_sub, profile_dir)
    # Another computer's older catalog won the config sync: v1 again.
    write_catalog(col, Catalog((replace(v1_sub, received={}),)))
    (lagging,) = read_catalog(col).subscriptions
    assert lagging.installed_version == "1"

    v3 = build_deck("3")
    v3["notes"][1]["fields"]["Back"] = "minou"
    server.publish(v3)
    updated, plan = run(col, server, lagging, profile_dir)

    assert plan.skipped == ()
    assert plan.counts.updated == 1
    assert must_note(col, "hw-reversed-1")["Back"] == "minou"
    assert updated.installed_version == "3"


def test_download_needs_no_collection_and_apply_no_network(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    installed, _ = run(col, server, sub, profile_dir)
    blue = png_bytes(0, 0, 255)
    deck = build_deck("2", image=blue)
    deck["notes"].append(basic_note("hw-basic-2", "new", "note"))
    server.publish(deck, blue)
    files = sorted(p.name for p in Path(col.media.dir()).iterdir())

    download = adapter.download_update(installed, transport=server)

    assert download.deck["deck"]["version"] == "2"
    assert [(e["filename"], data) for e, data in download.media] == [("h.png", blue)]
    assert sorted(p.name for p in Path(col.media.dir()).iterdir()) == files
    requests = len(server.requests)
    updated, plan = adapter.apply_download(
        col,
        installed,
        download,
        profile_dir=profile_dir,
        confirmed_full_sync=False,
        undo_label=LABEL,
    )
    assert len(server.requests) == requests
    assert plan.counts.created == 1
    assert updated.installed_version == "2"
    assert updated.etag == download.etag
    local = updated.media["h.png"].local_name
    assert (Path(col.media.dir()) / local).read_bytes() == blue


def test_held_download_writes_no_media(
    col: Collection, server: FakeServer, sub: Subscription, profile_dir: Path
) -> None:
    installed, _ = run(col, server, sub, profile_dir)
    blue = png_bytes(0, 0, 255)
    deck = build_deck("2", image=blue)
    deck["notetypes"][0]["fields"].append("Notes")
    deck["notetypes"][0]["templates"][0]["back"] += "{{Notes}}"
    deck["notes"][0]["fields"]["Notes"] = "a note"
    server.publish(deck, blue)
    download = adapter.download_update(installed, transport=server)
    files = sorted(p.name for p in Path(col.media.dir()).iterdir())

    returned, plan = adapter.apply_download(
        col,
        installed,
        download,
        profile_dir=profile_dir,
        confirmed_full_sync=False,
        undo_label=LABEL,
    )

    assert plan.needs_full_sync_confirmation
    assert returned == installed
    assert sorted(p.name for p in Path(col.media.dir()).iterdir()) == files
