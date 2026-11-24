from dataclasses import replace

from deckdock.format import CompiledDeck, MediaEntry, Note, Notetype

from deckdock_addon.engine import (
    Counts,
    LocalNote,
    LocalNotetype,
    LocalState,
    NoteAction,
    Plan,
    Skipped,
    make_plan,
    summary_lines,
    to_local_names,
    to_origin_names,
)
from deckdock_addon.store import MediaRecord, Received, Subscription, fingerprint

NT_ID = 100
DELETED = "DeckDock::Deleted"


def notetype(
    fields: tuple[str, ...] = ("Front", "Back"),
    templates: int = 1,
    kind: str = "standard",
    slug: str = "basic",
    name: str = "Basic",
) -> Notetype:
    return {
        "id": slug,
        "name": name,
        "kind": "cloze" if kind == "cloze" else "standard",
        "fields": list(fields),
        "templates": [
            {"name": f"Card {i + 1}", "front": "{{Front}}", "back": "{{Back}}"}
            for i in range(templates)
        ],
        "css": ".card {}",
    }


def note(
    guid: str,
    front: str = "q",
    back: str = "a",
    tags: tuple[str, ...] = (),
    deck: str = "Sub",
) -> Note:
    return {
        "guid": guid,
        "notetype": "basic",
        "deck": deck,
        "fields": {"Front": front, "Back": back},
        "tags": list(tags),
    }


def make_deck(
    notes: list[Note],
    notetypes: list[Notetype] | None = None,
    media: list[MediaEntry] | None = None,
) -> CompiledDeck:
    return {
        "format": "deckdock/1",
        "deck": {
            "id": "deck-1",
            "edition": "fr",
            "name": "Deck",
            "language": ["fr"],
            "version": "2",
        },
        "notetypes": notetypes if notetypes is not None else [notetype()],
        "notes": notes,
        "media": media or [],
    }


def make_sub(
    received: dict[str, Received] | None = None,
    media: dict[str, MediaRecord] | None = None,
    notetype_ids: dict[str, int] | None = None,
) -> Subscription:
    return Subscription(
        id="s1",
        source_url="https://github.com/o/r",
        base_url="https://example.com/fr/",
        deck_id="deck-1",
        edition="fr",
        name="Deck",
        notetype_ids={"basic": NT_ID} if notetype_ids is None else notetype_ids,
        media=media or {},
        received=received or {},
    )


def rec(front: str = "q", back: str = "a", tags: tuple[str, ...] = ()) -> Received:
    return Received(fingerprint({"Front": front, "Back": back}), tags)


def local_note(
    guid: str,
    front: str = "q",
    back: str = "a",
    tags: tuple[str, ...] = (),
    note_id: int = 1,
    mid: int = NT_ID,
) -> LocalNote:
    return LocalNote(note_id, guid, mid, {"Front": front, "Back": back}, tags)


def local_state(
    notes: list[LocalNote] | None = None,
    notetypes: dict[int, LocalNotetype] | None = None,
) -> LocalState:
    nts = (
        {NT_ID: LocalNotetype(NT_ID, ("Front", "Back"), 1, False)}
        if notetypes is None
        else notetypes
    )
    return LocalState({n.guid: n for n in notes or []}, nts, True)


def only_action(plan: Plan) -> NoteAction:
    assert len(plan.note_actions) == 1, plan.note_actions
    return plan.note_actions[0]


def only_skip(plan: Plan) -> Skipped:
    assert len(plan.skipped) == 1, plan.skipped
    return plan.skipped[0]


# --- notes (§5.4 notes table) ---


def test_create_unknown_guid() -> None:
    plan = make_plan(make_deck([note("g1", tags=("t",))]), make_sub(), local_state())
    a = only_action(plan)
    assert (a.kind, a.guid, a.note_id) == ("create", "g1", None)
    assert a.fields == {"Front": "q", "Back": "a"}
    assert a.tags == ("t",)
    assert (a.deck_path, a.notetype_slug) == ("Sub", "basic")
    assert plan.new_received == {"g1": rec(tags=("t",))}
    assert plan.counts.created == 1
    assert plan.blocked is None


def test_update_unmodified_note() -> None:
    plan = make_plan(
        make_deck([note("g1", back="new")]),
        make_sub({"g1": rec()}),
        local_state([local_note("g1", note_id=7)]),
    )
    a = only_action(plan)
    assert (a.kind, a.guid, a.note_id) == ("update", "g1", 7)
    assert a.fields == {"Front": "q", "Back": "new"}
    assert plan.new_received == {"g1": rec(back="new")}
    assert plan.counts.updated == 1
    assert plan.skipped == ()


def test_skip_modified_locally() -> None:
    plan = make_plan(
        make_deck([note("g1", back="new")]),
        make_sub({"g1": rec()}),
        local_state([local_note("g1", front="<b>my</b>   edit", back="a")]),
    )
    assert plan.note_actions == ()
    assert only_skip(plan) == Skipped("g1", "modified_locally", "my edit")
    assert plan.new_received == {"g1": rec()}
    assert plan.counts.skipped == 1


def test_do_not_recreate_deleted_locally() -> None:
    plan = make_plan(
        make_deck([note("g1", front="Hello <i>world</i>")]),
        make_sub({"g1": rec(front="Hello <i>world</i>")}),
        local_state(),
    )
    assert plan.note_actions == ()
    assert only_skip(plan) == Skipped("g1", "deleted_locally", "Hello world")
    assert plan.new_received == {"g1": rec(front="Hello <i>world</i>")}


def test_retire_missing_from_deck_adds_tag() -> None:
    plan = make_plan(
        make_deck([]),
        make_sub({"g1": rec(), "g2": rec(), "g3": rec()}),
        local_state(
            [
                local_note("g1", tags=("mine",), note_id=5),
                local_note("g3", tags=(DELETED,), note_id=6),
            ]
        ),
    )
    a = only_action(plan)
    assert (a.kind, a.guid, a.note_id) == ("retire", "g1", 5)
    assert a.tags == (DELETED, "mine")
    assert plan.new_received == {}
    assert plan.counts.retired == 1
    assert plan.skipped == ()


def test_no_base_equal_records_fingerprint() -> None:
    plan = make_plan(
        make_deck([note("g1", tags=("t",))]),
        make_sub(),
        local_state([local_note("g1", tags=("t",), note_id=3)]),
    )
    a = only_action(plan)
    assert (a.kind, a.guid, a.note_id) == ("record", "g1", 3)
    assert plan.new_received == {"g1": rec(tags=("t",))}
    c = plan.counts
    assert (c.created, c.updated, c.retired, c.skipped) == (0, 0, 0, 0)


def test_no_base_different_is_conflict() -> None:
    plan = make_plan(
        make_deck([note("g1")]),
        make_sub(),
        local_state([local_note("g1", front="older")]),
    )
    assert plan.note_actions == ()
    assert only_skip(plan) == Skipped("g1", "no_base_conflict", "older")
    assert plan.new_received == {}


def test_foreign_note_other_notetype_is_conflict() -> None:
    plan = make_plan(
        make_deck([note("g1")]),
        make_sub(),
        local_state([local_note("g1", mid=999)]),
    )
    assert plan.note_actions == ()
    assert only_skip(plan).reason == "foreign_note"
    assert plan.new_received == {}

    # Notetype not mapped yet (being created): any existing note is foreign.
    plan = make_plan(
        make_deck([note("g1")]),
        make_sub(notetype_ids={}),
        local_state([local_note("g1")], notetypes={}),
    )
    assert plan.note_actions == ()
    assert only_skip(plan).reason == "foreign_note"


def test_received_note_moved_to_other_notetype_is_modified_locally() -> None:
    plan = make_plan(
        make_deck([note("g1", back="new")]),
        make_sub({"g1": rec()}),
        local_state([local_note("g1", mid=999)]),
    )
    assert plan.note_actions == ()
    assert only_skip(plan).reason == "modified_locally"


def test_unchanged_note_no_action() -> None:
    plan = make_plan(
        make_deck([note("g1", tags=("t",))]),
        make_sub({"g1": rec(tags=("t",))}),
        local_state([local_note("g1", tags=("t", "marked"))]),
    )
    assert plan.note_actions == ()
    assert plan.skipped == ()
    assert plan.new_received == {"g1": rec(tags=("t",))}


# --- tags ---


def test_tags_user_tags_kept_and_received_replaced() -> None:
    plan = make_plan(
        make_deck([note("g1", tags=("new", "keep"))]),
        make_sub({"g1": rec(tags=("old", "keep"))}),
        local_state([local_note("g1", tags=("old", "keep", "leech", "marked"))]),
    )
    a = only_action(plan)
    assert a.kind == "update"
    assert a.tags == ("keep", "leech", "marked", "new")
    assert plan.new_received["g1"].tags == ("keep", "new")


def test_deckdock_tags_ignored_in_comparison() -> None:
    # Plugin tags do not make a note look modified and are not user tags.
    plan = make_plan(
        make_deck([note("g1")]),
        make_sub({"g1": rec()}),
        local_state([local_note("g1", tags=("DeckDock::Other", "mine"))]),
    )
    assert plan.note_actions == ()
    assert plan.skipped == ()

    # A retired note that reappears in the deck loses DeckDock::Deleted.
    plan = make_plan(
        make_deck([note("g1", tags=("t",))]),
        make_sub(),
        local_state([local_note("g1", tags=(DELETED, "mine", "t"), note_id=4)]),
    )
    a = only_action(plan)
    assert (a.kind, a.note_id) == ("update", 4)
    assert a.tags == ("mine", "t")
    assert plan.new_received == {"g1": rec(tags=("t",))}


# --- notetypes ---


def test_notetype_create_and_update_by_position() -> None:
    other = notetype(slug="other", name="Other")
    other["anki_id"] = 1234
    plan = make_plan(
        make_deck([note("g1")], notetypes=[notetype(), other]),
        make_sub(),
        local_state(),
    )
    changes = {(a.slug, a.change, a.anki_id) for a in plan.notetype_actions}
    assert changes == {("basic", "update", NT_ID), ("other", "create", 1234)}
    assert plan.needs_full_sync_confirmation is False
    assert plan.counts.notetypes_updated == 1

    # Deck anki_id that exists locally is reused.
    plan = make_plan(
        make_deck([], notetypes=[other]),
        make_sub(notetype_ids={}),
        local_state(notetypes={1234: LocalNotetype(1234, ("Front", "Back"), 1, False)}),
    )
    assert [(a.change, a.anki_id) for a in plan.notetype_actions] == [("update", 1234)]


def test_notetype_unchanged_when_templates_and_css_match() -> None:
    nt = notetype(fields=("Front", "Back"))
    nt["css"] = '.card { background: url("bg.png"); }'
    media = {"bg.png": MediaRecord("0" * 64, "bg-ab12.png")}
    local_nt = LocalNotetype(
        NT_ID,
        ("Front", "Back"),
        1,
        False,
        templates=(("Card 1", "{{Front}}", "{{Back}}"),),
        css='.card { background: url("bg-ab12.png"); }',
    )
    plan = make_plan(
        make_deck([], notetypes=[nt]),
        make_sub(media=media),
        local_state(notetypes={NT_ID: local_nt}),
    )
    assert [a.change for a in plan.notetype_actions] == ["unchanged"]
    assert plan.counts.notetypes_updated == 0

    changed = replace(local_nt, css=".card {}")
    plan = make_plan(
        make_deck([], notetypes=[nt]),
        make_sub(media=media),
        local_state(notetypes={NT_ID: changed}),
    )
    assert [a.change for a in plan.notetype_actions] == ["update"]


def test_append_fields_needs_confirmation() -> None:
    nt = notetype(fields=("Front", "Back", "Extra", "More"))
    n = note("g1")
    n["fields"] = {"Front": "q", "Back": "a", "Extra": "x", "More": ""}
    plan = make_plan(
        make_deck([n], notetypes=[nt]),
        make_sub({"g1": rec()}),
        local_state([local_note("g1")]),
    )
    assert plan.blocked is None
    (nta,) = plan.notetype_actions
    assert (nta.change, nta.anki_id, nta.appended_fields) == (
        "append_fields",
        NT_ID,
        ("Extra", "More"),
    )
    assert plan.needs_full_sync_confirmation is True
    assert only_action(plan).kind == "update"
    assert plan.counts.notetypes_updated == 1


def test_removed_renamed_reordered_field_blocks() -> None:
    for fields in (("Front",), ("Front", "Verso"), ("Back", "Front")):
        plan = make_plan(
            make_deck([note("g1")], notetypes=[notetype(fields=fields)]),
            make_sub({"g1": rec()}),
            local_state([local_note("g1")]),
        )
        assert plan.blocked is not None, fields
        assert "Basic" in plan.blocked


def test_template_count_change_blocks() -> None:
    for count, local_count in ((2, 1), (1, 2)):
        plan = make_plan(
            make_deck([], notetypes=[notetype(templates=count)]),
            make_sub(),
            local_state(
                notetypes={
                    NT_ID: LocalNotetype(NT_ID, ("Front", "Back"), local_count, False)
                }
            ),
        )
        assert plan.blocked is not None


def test_kind_change_blocks() -> None:
    plan = make_plan(
        make_deck([], notetypes=[notetype(kind="cloze")]),
        make_sub(),
        local_state(),
    )
    assert plan.blocked is not None
    assert "Basic" in plan.blocked


def test_blocked_plan_has_no_actions() -> None:
    received = {"g1": rec(), "gone": rec()}
    plan = make_plan(
        make_deck(
            [note("g1", back="new"), note("g2")],
            notetypes=[notetype(fields=("Back", "Front"))],
            media=[{"filename": "a.png", "sha256": "1" * 64, "size": 3}],
        ),
        make_sub(received),
        local_state([local_note("g1"), local_note("gone", note_id=2)]),
    )
    assert plan.blocked is not None
    assert plan.notetype_actions == ()
    assert plan.note_actions == ()
    assert plan.skipped == ()
    assert plan.media_to_download == ()
    assert plan.new_received == received
    assert plan.needs_full_sync_confirmation is False
    assert plan.counts == Counts(0, 0, 0, 0, 0)


# --- media ---


def test_media_to_download_new_or_changed_sha() -> None:
    same: MediaEntry = {"filename": "same.png", "sha256": "a" * 64, "size": 1}
    changed: MediaEntry = {"filename": "changed.png", "sha256": "b" * 64, "size": 1}
    new: MediaEntry = {"filename": "new.png", "sha256": "c" * 64, "size": 1}
    media = {
        "same.png": MediaRecord("a" * 64, "same.png"),
        "changed.png": MediaRecord("0" * 64, "changed.png"),
    }
    plan = make_plan(
        make_deck([], media=[same, changed, new]), make_sub(media=media), local_state()
    )
    assert plan.media_to_download == (changed, new)


def test_local_media_names_do_not_look_modified() -> None:
    media = {"h.png": MediaRecord("a" * 64, "h-ad78.png")}
    plan = make_plan(
        make_deck([note("g1", front='<img src="h.png">', back="new")]),
        make_sub({"g1": rec(front='<img src="h.png">')}, media=media),
        local_state([local_note("g1", front='<img src="h-ad78.png">')]),
    )
    a = only_action(plan)
    assert a.kind == "update"
    # Actions carry origin names; the adapter rewrites them to local names.
    assert a.fields == {"Front": '<img src="h.png">', "Back": "new"}
    assert plan.skipped == ()


def test_to_local_names_rewrites_src_sound_url() -> None:
    media = {
        "h.png": MediaRecord("a" * 64, "h-ad78.png"),
        "s.mp3": MediaRecord("b" * 64, "s-11.mp3"),
        "bg.png": MediaRecord("c" * 64, "bg-22.png"),
        "my file.png": MediaRecord("d" * 64, "my file-33.png"),
        "same.png": MediaRecord("e" * 64, "same.png"),
    }
    text = (
        "<img SRC=\"h.png\"> <img src='h.png'> [sound:s.mp3] [SOUND:s.mp3] "
        "div { background: URL( 'bg.png' ) } url(bg.png) "
        '<img src="my%20file.png"> <img src="unknown.png"> '
        '<img src="https://x/h.png"> <img src="same.png">'
    )
    expected = (
        "<img SRC=\"h-ad78.png\"> <img src='h-ad78.png'> [sound:s-11.mp3] [SOUND:s.mp3] "
        "div { background: URL( 'bg-22.png' ) } url(bg-22.png) "
        '<img src="my%20file-33.png"> <img src="unknown.png"> '
        '<img src="https://x/h.png"> <img src="same.png">'
    )
    assert to_local_names(text, media) == expected
    assert to_origin_names(expected, media) == text
    assert to_local_names("no refs &amp; text", media) == "no refs &amp; text"


# --- summary ---


def test_counts_and_summary_fr_en() -> None:
    nt = notetype(fields=("Front", "Back", "Extra"))
    notes = [note(g) for g in ("c1", "c2", "c3", "u1", "m1", "d1")]
    for n in notes:
        n["fields"]["Extra"] = ""
    notes[3]["fields"]["Back"] = "new"
    plan = make_plan(
        make_deck(notes, notetypes=[nt]),
        make_sub({g: rec() for g in ("u1", "m1", "d1", "r1")}),
        local_state(
            [
                local_note("u1", note_id=1),
                local_note("m1", back="mine", note_id=2),
                local_note("r1", note_id=3),
            ]
        ),
    )
    assert plan.counts.created == 3
    assert plan.counts.updated == 1
    assert plan.counts.retired == 1
    assert plan.counts.skipped == 2
    assert plan.counts.notetypes_updated == 1

    fr = "\n".join(summary_lines(plan, "Deck", "fr", "fr"))
    assert "Deck (fr)" in fr
    assert "3 nouvelles" in fr
    assert "1 mise à jour" in fr
    assert "1 retirée" in fr
    assert "1 modifiée par toi" in fr
    assert "1 supprimée par toi" in fr
    assert "notetypes : 1 mis à jour" in fr
    assert (
        "Cette mise à jour ajoute un champ au type de carte Basic. Anki demandera une "
        "synchronisation complète : synchronise d'abord tes autres appareils (téléphone, "
        "tablette), puis confirme."
    ) in fr

    en = "\n".join(summary_lines(plan, "Deck", "fr", "en"))
    assert "3 new" in en
    assert "1 updated" in en
    assert "1 retired" in en
    assert "1 modified by you" in en
    assert "1 deleted by you" in en
    assert "full sync" in en
    assert "Basic" in en

    blocked = make_plan(
        make_deck([], notetypes=[notetype(kind="cloze")]), make_sub(), local_state()
    )
    assert blocked.blocked is not None
    assert blocked.blocked in "\n".join(summary_lines(blocked, "Deck", "fr", "en"))
    assert "non pris en charge" in "\n".join(summary_lines(blocked, "Deck", "fr", "fr"))

    empty = make_plan(make_deck([]), make_sub(), local_state())
    assert summary_lines(empty, "Deck", "fr", "de")[0].startswith("Deck (fr)")


def test_tag_only_change_updates_tags() -> None:
    plan = make_plan(
        make_deck([note("g1", tags=("b",))]),
        make_sub({"g1": rec(tags=("a",))}),
        local_state([local_note("g1", tags=("a", "mine"))]),
    )
    a = only_action(plan)
    assert (a.kind, a.tags) == ("update", ("b", "mine"))


def test_media_names_html_escaped_round_trip() -> None:
    media = {"a&b.png": MediaRecord("a" * 64, "a&b-1.png")}
    text = '<img src="a&amp;b.png"> [sound:a&b.png]'
    local = to_local_names(text, media)
    assert local == '<img src="a&amp;b-1.png"> [sound:a&b-1.png]'
    assert to_origin_names(local, media) == text
