"""Anki adapter: read the local state of a subscription and execute an engine plan.

This is the only module that writes into the user's collection. Media files are
written first, outside the collection operation, and never overwrite a file.
Every collection change of one update (notetypes, decks, notes and the persisted
subscription) is merged into a single undo entry. What could make a collection
step fail is checked before the first write; if a step still fails, the steps
already done are undone, or `PartialApplyError` reports that they could not be.
An update with nothing to change in the collection creates no undo entry.

The received fingerprints live in a file of the media folder (see `store`). It
is read before every plan and written after a successful apply, outside the
undo entry: undoing restores the previous `installed_version`, whose snapshot
the file still holds.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

from anki.collection import AddNoteRequest, Collection
from anki.dbproxy import DBProxy
from anki.decks import DeckId
from anki.models import NotetypeDict, NotetypeId
from anki.notes import Note as AnkiNote
from anki.notes import NoteId
from deckdock.format import CompiledDeck, MediaEntry, Notetype

from deckdock_addon.engine import (
    DELETED_TAG,
    LocalNote,
    LocalNotetype,
    LocalState,
    NoteAction,
    NotetypeAction,
    Plan,
    Skipped,
    make_plan,
    preview,
    received_fingerprint,
    received_missing_plan,
    to_local_names,
)
from deckdock_addon.sources import SourceError, Transport, fetch_deck, fetch_media
from deckdock_addon.store import (
    CONFIG_KEY,
    Catalog,
    MediaRecord,
    Subscription,
    dump_catalog,
    full_versions_path,
    read_catalog,
    read_full_versions,
    read_received,
    received_path,
    write_full_versions,
    write_received,
)

_log = logging.getLogger(__name__)

SQL_CHUNK = 500
_MODEL_CLOZE = 1
_FIELD_SEPARATOR = "\x1f"


def notetype_name(deck: CompiledDeck, nt: Notetype) -> str:
    """Anki name of a deck notetype (only used at creation; found by id afterwards)."""
    info = deck["deck"]
    return f"{info['name']} ({info['edition']}) · {nt['name']}"


def _chunks(items: Sequence[str], size: int = SQL_CHUNK) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _db(col: Collection) -> DBProxy:
    db = col.db
    if db is None:
        raise ValueError("the collection is closed")
    return db


def _deck_exists(col: Collection, did: int | None) -> bool:
    if did is None:
        return False
    found = col.decks.get(DeckId(did), default=False)
    return found is not None and not found.get("dyn")


# --- reading -----------------------------------------------------------------------


def _local_notetype(nt: NotetypeDict) -> LocalNotetype:
    tmpls = cast(list[dict[str, object]], nt["tmpls"])
    flds = cast(list[dict[str, object]], nt["flds"])
    return LocalNotetype(
        anki_id=cast(int, nt["id"]),
        field_names=tuple(str(f["name"]) for f in flds),
        template_count=len(tmpls),
        is_cloze=cast(int, nt["type"]) == _MODEL_CLOZE,
        templates=tuple(
            (str(t["name"]), str(t["qfmt"]), str(t["afmt"])) for t in tmpls
        ),
        css=cast(str, nt["css"]),
    )


def read_local_state(
    col: Collection, deck: CompiledDeck, sub: Subscription
) -> LocalState:
    """Notes whose GUID is in the deck or was received, and the relevant notetypes.

    `sub.received` must hold the received file's snapshot (`with_received`).
    Notes are read with one SQL query per chunk of 500 GUIDs.
    """
    guids = sorted({n["guid"] for n in deck["notes"]} | set(sub.received))
    rows: list[tuple[int, str, int, str, str]] = []
    for chunk in _chunks(guids):
        marks = ",".join("?" * len(chunk))
        sql = f"select id, guid, mid, flds, tags from notes where guid in ({marks})"
        rows.extend(
            cast(tuple[int, str, int, str, str], tuple(r))
            for r in _db(col).all(sql, *chunk)
        )

    wanted = {mid for _, _, mid, _, _ in rows}
    wanted.update(sub.notetype_ids.values())
    wanted.update(a for nt in deck["notetypes"] if (a := nt.get("anki_id")) is not None)
    notetypes: dict[int, LocalNotetype] = {}
    for mid in wanted:
        nt = col.models.get(NotetypeId(mid))
        if nt is not None:
            notetypes[mid] = _local_notetype(nt)

    notes: dict[str, LocalNote] = {}
    for nid, guid, mid, flds, tags in rows:
        values = flds.split(_FIELD_SEPARATOR)
        loc = notetypes.get(mid)
        names = loc.field_names if loc is not None else ()
        names = names + tuple(f"field {i}" for i in range(len(names), len(values)))
        notes[guid] = LocalNote(
            note_id=nid,
            guid=guid,
            notetype_anki_id=mid,
            fields=dict(zip(names, values, strict=False)),
            tags=tuple(tags.split()),
        )

    info = deck["deck"]
    root_exists = _deck_exists(col, sub.root_deck_anki_id) or _deck_exists(
        col, info.get("anki_id")
    )
    return LocalState(notes, notetypes, root_exists)


def browser_search(col: Collection, guids: Sequence[str]) -> str | None:
    """A Browser search for the notes with these GUIDs, or None when none exists.

    Anki has no search on the GUID (`guid:` searches a field named "guid"), so
    the GUIDs are resolved to note ids, one SQL query per chunk of 500.
    """
    ids: set[int] = set()
    for chunk in _chunks(sorted(set(guids))):
        marks = ",".join("?" * len(chunk))
        sql = f"select id from notes where guid in ({marks})"
        ids.update(cast(list[int], _db(col).list(sql, *chunk)))
    return "nid:" + ",".join(str(i) for i in sorted(ids)) if ids else None


# --- media -------------------------------------------------------------------------


def write_media(
    col: Collection,
    entries: Iterable[tuple[MediaEntry, bytes]],
    media: dict[str, MediaRecord],
) -> dict[str, MediaRecord]:
    """Write downloaded media; return the media table with the local names Anki chose.

    `col.media.write_data` never replaces an existing file: when another file
    already has the name, Anki stores the data under a new name and returns it.
    """
    out = dict(media)
    for entry, data in entries:
        local = col.media.write_data(entry["filename"], data)
        out[entry["filename"]] = MediaRecord(entry["sha256"], local)
    return out


# --- applying ----------------------------------------------------------------------


class ApplyRefusedError(Exception):
    """The plan cannot be applied safely; nothing was written to the collection.

    `code` is stable for the interface: "deck_name_conflict" (a deck to create is
    named like an existing filtered deck) or "collection_changed" (a note or
    notetype of the plan disappeared since the plan was made: check again).
    """

    code: str

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class PartialApplyError(Exception):
    """A collection step failed and the steps already done could not be undone.

    The subscription was not updated. Running the update again finishes it:
    notetypes and decks left by the failed attempt are found again and reused.
    The original error is chained as `__cause__`.
    """

    code: str = "partial_apply"

    def __init__(self) -> None:
        super().__init__(
            "The update was partially applied and could not be undone; run Check "
            + "again to finish it."
        )


def _compatible(nt_dict: NotetypeDict, nt: Notetype) -> bool:
    """Whether an existing notetype has exactly the structure of the deck notetype."""
    loc = _local_notetype(nt_dict)
    return (
        loc.field_names == tuple(nt["fields"])
        and loc.template_count == len(nt["templates"])
        and loc.is_cloze == (nt["kind"] == "cloze")
    )


MARKER_KEY = "deckdock"


def notetype_marker(deck: CompiledDeck, slug: str) -> dict[str, str]:
    """Identity stamped into every notetype DeckDock creates (key `deckdock`).

    Anki keeps unknown top-level notetype keys through add, update, sync and
    reopening (verified on 26.9.4), so a notetype is recognized by the deck,
    edition and slug that created it, never by its name.
    """
    info = deck["deck"]
    return {"deck_id": info["id"], "edition": info["edition"], "slug": slug}


def foreign_notetype_ids(catalog: Catalog, sub: Subscription) -> frozenset[int]:
    """Notetype ids mapped by the other subscriptions of the catalog."""
    return frozenset(
        anki_id
        for other in catalog.subscriptions
        if other.id != sub.id
        for anki_id in other.notetype_ids.values()
    )


def _find_by_marker(
    col: Collection, deck: CompiledDeck, nt: Notetype, exclude: frozenset[int]
) -> int | None:
    """Id of a notetype created by DeckDock for this deck notetype, same structure."""
    marker = notetype_marker(deck, nt["id"])
    for entry in col.models.all_names_and_ids():
        if entry.id in exclude:
            continue
        found = col.models.get(NotetypeId(entry.id))
        if found is None or found.get(MARKER_KEY) != marker:
            continue
        if _compatible(found, nt):
            return int(entry.id)
    return None


def adopt_notetypes(
    col: Collection,
    deck: CompiledDeck,
    sub: Subscription,
    exclude: frozenset[int] | None = None,
) -> Subscription:
    """Map deck notetypes that lost their mapping to the notetype DeckDock made.

    A notetype whose remembered id is missing, and whose deck `anki_id` is not in
    the collection, is looked up by its DeckDock marker (deck id, edition, slug)
    and structure, skipping the ids in `exclude` (those of other
    subscriptions). This recovers the notetypes created by an interrupted
    update, so a retry never creates duplicates, and its notes are recognized
    as this deck's. Notetypes of other decks or of the user are never taken.
    """
    ids = dict(sub.notetype_ids)
    for nt in deck["notetypes"]:
        mapped = ids.get(nt["id"])
        if mapped is not None and col.models.get(NotetypeId(mapped)) is not None:
            continue
        anki_id = nt.get("anki_id")
        if anki_id is not None and col.models.get(NotetypeId(anki_id)) is not None:
            continue
        found = _find_by_marker(col, deck, nt, exclude or frozenset())
        if found is not None:
            ids[nt["id"]] = found
    return sub if ids == sub.notetype_ids else replace(sub, notetype_ids=ids)


class _Applier:
    def __init__(
        self, col: Collection, deck: CompiledDeck, sub: Subscription, plan: Plan
    ) -> None:
        self.col: Collection = col
        self.deck: CompiledDeck = deck
        self.sub: Subscription = sub
        self.plan: Plan = plan
        self.notetypes: dict[str, Notetype] = {nt["id"]: nt for nt in deck["notetypes"]}
        self.ids: dict[str, int] = dict(sub.notetype_ids)
        self.imposed: set[str] = set()
        self.creates: list[NoteAction] = [
            a for a in plan.note_actions if a.kind == "create"
        ]
        self.changes: list[NoteAction] = [
            a for a in plan.note_actions if a.kind in ("update", "retire")
        ]
        self.catalog: Catalog = Catalog()
        self.root: int | None = None
        self.taken: set[str] = set()
        self.pos: int | None = None
        self.done: int = 0

    def local(self, text: str) -> str:
        return to_local_names(text, self.sub.media)

    def merge(self) -> None:
        """Record that a collection step succeeded and merge it into the undo entry."""
        self.done += 1
        if self.pos is not None:
            _ = self.col.merge_undo_entries(self.pos)

    # validation (no writes)

    def _deck_problem(self, name: str) -> None:
        parts = name.split("::")
        for i in range(1, len(parts) + 1):
            prefix = "::".join(parts[:i])
            did = self.col.decks.id_for_name(prefix)
            if did is None:
                continue
            found = self.col.decks.get(did, default=False)
            if found is not None and found.get("dyn"):
                raise ApplyRefusedError(
                    "deck_name_conflict",
                    f"the deck {prefix!r} is a filtered deck; rename it and check again",
                )

    def _resolve_root(self) -> tuple[int | None, str]:
        """Existing root deck id (remembered id, deck `anki_id`, then name) and its name."""
        info = self.deck["deck"]
        for did in (self.sub.root_deck_anki_id, info.get("anki_id")):
            if did is not None and _deck_exists(self.col, did):
                return did, self.col.decks.name(DeckId(did))
        did = self.col.decks.id_for_name(info["name"])
        if did is not None and _deck_exists(self.col, did):
            return int(did), info["name"]
        return None, info["name"]

    def validate(self) -> None:
        """Refuse, before any write, what would make a collection step fail."""
        self.catalog = read_catalog(self.col)
        mm = self.col.models
        for action in self.plan.notetype_actions:
            if action.change == "create":
                continue
            if action.anki_id is None or mm.get(NotetypeId(action.anki_id)) is None:
                raise ApplyRefusedError(
                    "collection_changed", f"note type {action.slug!r} is missing"
                )
        expected = {a.note_id: a.guid for a in self.changes if a.note_id is not None}
        found: dict[int, str] = {}
        ids = [str(i) for i in expected]
        for chunk in _chunks(ids):
            marks = ",".join("?" * len(chunk))
            sql = f"select id, guid from notes where id in ({marks})"
            for row in _db(self.col).all(sql, *(int(i) for i in chunk)):
                found[cast(int, row[0])] = cast(str, row[1])
        if any(found.get(nid) != guid for nid, guid in expected.items()):
            raise ApplyRefusedError("collection_changed", "a note to update is missing")

        self.taken = self.taken_guids([a.guid for a in self.creates])
        if any(a.guid not in self.taken for a in self.creates):
            root, root_name = self._resolve_root()
            self.root = root
            if root is None:
                self._deck_problem(root_name)
            for path in {a.deck_path or "" for a in self.creates} - {""}:
                self._deck_problem(f"{root_name}::{path}")
        else:
            self.root, _ = self._resolve_root()

    def taken_guids(self, guids: list[str]) -> set[str]:
        taken: set[str] = set()
        for chunk in _chunks(guids):
            marks = ",".join("?" * len(chunk))
            sql = f"select guid from notes where guid in ({marks})"
            taken.update(cast(list[str], _db(self.col).list(sql, *chunk)))
        return taken

    def writes_collection(self) -> bool:
        return (
            bool(self.changes)
            or any(a.guid not in self.taken for a in self.creates)
            or any(a.change != "unchanged" for a in self.plan.notetype_actions)
        )

    # notetypes

    def _set_templates(self, nt_dict: NotetypeDict, nt: Notetype) -> None:
        tmpls = cast(list[dict[str, object]], nt_dict["tmpls"])
        for tmpl, template in zip(tmpls, nt["templates"], strict=True):
            tmpl["name"] = template["name"]
            tmpl["qfmt"] = self.local(template["front"])
            tmpl["afmt"] = self.local(template["back"])
        nt_dict["css"] = self.local(nt["css"])

    def _new_notetype(self, nt: Notetype) -> NotetypeDict:
        mm = self.col.models
        nt_dict = mm.new(notetype_name(self.deck, nt))
        nt_dict[MARKER_KEY] = notetype_marker(self.deck, nt["id"])
        if nt["kind"] == "cloze":
            nt_dict["type"] = _MODEL_CLOZE
        for name in nt["fields"]:
            mm.add_field(nt_dict, mm.new_field(name))
        for template in nt["templates"]:
            mm.add_template(nt_dict, mm.new_template(template["name"]))
        self._set_templates(nt_dict, nt)
        return nt_dict

    def create_with_imposed_ids(self) -> None:
        """Create the notetypes whose deck `anki_id` is free, with that id.

        Anki only accepts an imposed id through the legacy `models.update` with
        `preserve_usn=True`, which is not undoable and clears the undo queue, so
        this runs before the undo entry is opened. The usn is set to -1 so the
        notetype is sent on the next sync.
        """
        for action in self.plan.notetype_actions:
            if action.change != "create" or action.anki_id is None:
                continue
            if self.col.models.get(NotetypeId(action.anki_id)) is not None:
                continue
            nt_dict = self._new_notetype(self.notetypes[action.slug])
            nt_dict["id"] = action.anki_id
            nt_dict["usn"] = -1
            nt_dict["mod"] = int(time.time())
            self.col.models.update(nt_dict, preserve_usn=True)
            self.ids[action.slug] = action.anki_id
            self.imposed.add(action.slug)

    def _update_notetype(
        self, anki_id: int, nt: Notetype, appended: Iterable[str]
    ) -> None:
        mm = self.col.models
        nt_dict = mm.get(NotetypeId(anki_id))
        if nt_dict is None:
            raise ApplyRefusedError(
                "collection_changed", f"note type {nt['id']!r} is missing"
            )
        for name in appended:
            mm.add_field(nt_dict, mm.new_field(name))
        self._set_templates(nt_dict, nt)
        _ = mm.update_dict(nt_dict)
        self.merge()

    def apply_notetype(self, action: NotetypeAction) -> None:
        nt = self.notetypes[action.slug]
        if action.change == "create":
            if action.slug in self.imposed:
                return  # already created with its imposed id
            exclude = foreign_notetype_ids(self.catalog, self.sub)
            found = _find_by_marker(self.col, self.deck, nt, exclude)
            if found is not None:  # left by an interrupted attempt
                self.ids[action.slug] = found
                self._update_notetype(found, nt, ())
                return
            self.ids[action.slug] = int(self.col.models.add(self._new_notetype(nt)).id)
            self.merge()
            return
        if action.anki_id is None:
            raise ApplyRefusedError("collection_changed", f"note type {action.slug!r}")
        self.ids[action.slug] = action.anki_id
        if action.change != "unchanged":
            self._update_notetype(action.anki_id, nt, action.appended_fields)

    # decks

    def root_deck(self) -> int:
        if self.root is not None:
            return self.root
        name = self.deck["deck"]["name"]
        did = self.col.decks.id(name)
        if did is None:
            raise ValueError(f"cannot create deck {name!r}")
        self.merge()
        self.root = int(did)
        return self.root

    def deck_ids(self, root: int, paths: set[str]) -> dict[str, int]:
        root_name = self.col.decks.name(DeckId(root))
        out = {"": root}
        for path in sorted(paths - {""}):
            did = self.col.decks.id(f"{root_name}::{path}")
            if did is None:
                raise ValueError(f"cannot create deck {path!r}")
            out[path] = int(did)
            self.merge()
        return out

    # notes

    def taken_skips(self) -> list[Skipped]:
        """Creations refused because another note already has the GUID."""
        return [
            Skipped(
                a.guid,
                "foreign_note",
                preview(next(iter((a.fields or {}).values()), "")),
            )
            for a in self.creates
            if a.guid in self.taken
        ]

    def create_notes(self) -> list[Skipped]:
        skipped = self.taken_skips()
        todo = [a for a in self.creates if a.guid not in self.taken]
        if not todo:
            return skipped
        decks = self.deck_ids(self.root_deck(), {a.deck_path or "" for a in todo})
        models: dict[str, NotetypeDict] = {}
        requests: list[AddNoteRequest] = []
        for a in todo:
            slug = a.notetype_slug or ""
            if slug not in models:
                nt_dict = self.col.models.get(NotetypeId(self.ids[slug]))
                if nt_dict is None:
                    raise ValueError(f"notetype {slug!r} not found")
                models[slug] = nt_dict
            note = self.col.new_note(models[slug])
            note.guid = a.guid
            for name, value in (a.fields or {}).items():
                note[name] = self.local(value)
            note.tags = list(a.tags or ())
            requests.append(AddNoteRequest(note, DeckId(decks[a.deck_path or ""])))
        _ = self.col.add_notes(requests)
        self.merge()
        return skipped

    def change_notes(self) -> None:
        changed: list[AnkiNote] = []
        for a in self.changes:
            if a.note_id is None:
                continue
            note = self.col.get_note(NoteId(a.note_id))
            if a.kind == "retire":
                note.add_tag(DELETED_TAG)
            else:
                for name, value in (a.fields or {}).items():
                    note[name] = self.local(value)
                note.tags = list(a.tags or ())
            changed.append(note)
        if changed:
            _ = self.col.update_notes(changed)
            self.merge()

    # subscription

    def new_subscription(self, extra: Iterable[Skipped]) -> Subscription:
        received = dict(self.plan.new_received)
        for s in extra:
            _ = received.pop(s.guid, None)
        return replace(
            self.sub,
            installed_version=self.deck["deck"]["version"],
            available_version=None,
            notetype_ids=self.ids,
            root_deck_anki_id=self.root
            if self.root is not None
            else self.sub.root_deck_anki_id,
            received=received,
        )

    def persist(self, sub: Subscription, *, undoable: bool) -> None:
        """Store the subscription in the collection config.

        Inside the undo entry, undoing the update also restores the previous
        `installed_version`, whose received snapshot the media folder file still
        holds, so undone notes are not later mistaken for notes deleted by the
        user.
        """
        subs = self.catalog.subscriptions
        sub = replace(sub, received={})  # kept in the media folder, not the config
        if any(s.id == sub.id for s in subs):
            if sub in subs:
                return
            subs = tuple(sub if s.id == sub.id else s for s in subs)
        else:
            subs = (*subs, sub)
        _ = self.col.set_config(
            CONFIG_KEY, dump_catalog(Catalog(subs)), undoable=undoable
        )
        if undoable:
            self.merge()

    def run(self, undo_label: str) -> tuple[Subscription, tuple[Skipped, ...]]:
        self.validate()
        extra_taken = self.taken_skips()
        if not self.writes_collection():
            # Nothing to change in the collection: no undo entry that would hide
            # the user's own last action.
            new_sub = self.new_subscription(extra_taken)
            self.persist(new_sub, undoable=False)
            return new_sub, tuple(extra_taken)

        self.create_with_imposed_ids()
        self.pos = self.col.add_custom_undo_entry(undo_label)
        try:
            for action in self.plan.notetype_actions:
                self.apply_notetype(action)
            extra = self.create_notes()
            self.change_notes()
            new_sub = self.new_subscription(extra)
            self.persist(new_sub, undoable=True)
        except BaseException as error:
            self.rollback(undo_label, error)
            raise
        return new_sub, tuple(extra)

    def rollback(self, undo_label: str, error: BaseException) -> None:
        """Undo the steps already done, or raise `PartialApplyError` from `error`.

        When an Anki backend operation fails, Anki may discard the whole undo
        queue; the steps already done then cannot be undone and the failure is
        reported as partial instead of being hidden.
        """
        try:
            if self.done == 0:
                # Nothing was applied: only drop the empty undo entry, if still there.
                if self.col.undo_status().undo == undo_label:
                    _ = self.col.undo()
                return
            _ = self.col.merge_undo_entries(cast(int, self.pos))
            if self.col.undo_status().undo != undo_label:
                raise PartialApplyError from error
            _ = self.col.undo()
        except PartialApplyError:
            raise
        except Exception as undo_error:  # noqa: BLE001 - recorded on the raised error
            if self.done == 0:
                error.add_note(f"Removing the empty undo entry failed: {undo_error!r}")
                return
            partial = PartialApplyError()
            partial.add_note(f"Undoing the applied steps failed: {undo_error!r}")
            raise partial from error


def apply_plan(
    col: Collection,
    deck: CompiledDeck,
    sub: Subscription,
    plan: Plan,
    *,
    undo_label: str,
    confirmed_full_sync: bool = False,
) -> tuple[Subscription, tuple[Skipped, ...]]:
    """Execute `plan` on the collection as one undo entry.

    `sub.media` must already hold the local names of the downloaded media (see
    `write_media`). Returns the updated subscription (also persisted in the
    collection config within the same undo entry) and the notes skipped at apply
    time because their GUID was taken by another note (`foreign_note`).

    Raises `ApplyRefusedError` (nothing written) when the plan cannot be applied
    safely, and `PartialApplyError` when a step failed and could not be undone.
    A plan with nothing to change in the collection only updates the stored
    subscription, without an undo entry.
    """
    if plan.blocked is not None:
        raise ValueError(f"refusing to apply a blocked plan: {plan.blocked}")
    if plan.needs_full_sync_confirmation and not confirmed_full_sync:
        raise ValueError("this plan needs the user to confirm a full sync")
    new_sub, extra = _Applier(col, deck, sub, plan).run(undo_label)
    _write_received(col, new_sub, base=sub.installed_version)
    return new_sub, extra


# --- received fingerprints ---------------------------------------------------------


def _received_file(col: Collection, sub: Subscription) -> Path:
    return received_path(Path(col.media.dir()), sub.deck_id, sub.edition)


def with_received(col: Collection, sub: Subscription) -> Subscription | None:
    """`sub` with the received fingerprints of its installed version.

    None when `sub` is installed but its received file is missing or unusable
    on this computer (see `store.read_received`).
    """
    path = _received_file(col, sub)
    received = read_received(path, sub.installed_version, sub.id)
    return None if received is None else replace(sub, received=received)


def _write_received(col: Collection, sub: Subscription, *, base: str | None) -> None:
    """Record the received fingerprints of the applied version, unless already there.

    `base` is the version installed before the apply; its snapshot is kept for
    an undo. A failure is only logged: the update itself is applied and persisted.
    """
    if sub.installed_version is None:
        return
    path = _received_file(col, sub)
    try:
        _ = write_received(
            path,
            sub.deck_id,
            sub.edition,
            sub.installed_version,
            sub.received,
            subscription=sub.id,
            base=base,
        )
    except OSError as error:
        _log.warning("DeckDock: could not write %s: %s", path, error)


# --- full pipeline -----------------------------------------------------------------


def _with_extra_skipped(plan: Plan, extra: tuple[Skipped, ...]) -> Plan:
    if not extra:
        return plan
    counts = replace(
        plan.counts,
        created=plan.counts.created - len(extra),
        skipped=plan.counts.skipped + len(extra),
    )
    return replace(plan, skipped=plan.skipped + extra, counts=counts)


def _write_versions(profile_dir: Path, deck: CompiledDeck, sub: Subscription) -> None:
    """Keep the received fields of every note whose received fingerprint is current."""
    path = full_versions_path(profile_dir, sub.id)
    previous = read_full_versions(path)
    versions = {g: f for g, f in previous.items() if g in sub.received}
    for n in deck["notes"]:
        rec = sub.received.get(n["guid"])
        if rec is not None and rec.fingerprint == received_fingerprint(n["fields"]):
            versions[n["guid"]] = dict(n["fields"])
    try:
        write_full_versions(path, versions)
    except OSError:
        # Full versions only serve the future three-way comparison; the update
        # itself has been applied and persisted, so it must not be reported failed.
        pass


def _held(plan: Plan, confirmed_full_sync: bool) -> bool:
    return plan.blocked is not None or (
        plan.needs_full_sync_confirmation and not confirmed_full_sync
    )


def _without_foreign_anki_ids(
    deck: CompiledDeck, exclude: frozenset[int]
) -> CompiledDeck:
    """The deck without notetype `anki_id`s that another subscription already maps.

    Such a notetype belongs to another deck: it is neither reused nor updated,
    and this deck gets its own notetype instead.
    """
    if not any(nt.get("anki_id") in exclude for nt in deck["notetypes"]):
        return deck
    notetypes: list[Notetype] = []
    for nt in deck["notetypes"]:
        copy = nt.copy()
        if copy.get("anki_id") in exclude:
            del copy["anki_id"]
        notetypes.append(copy)
    out = deck.copy()
    out["notetypes"] = notetypes
    return out


def _plan(
    col: Collection, deck: CompiledDeck, sub: Subscription, exclude: frozenset[int]
) -> tuple[Subscription, Plan]:
    loaded = with_received(col, sub)
    if loaded is None:
        return sub, received_missing_plan(deck, sub)
    base = adopt_notetypes(col, deck, loaded, exclude)
    return base, make_plan(deck, base, read_local_state(col, deck, base))


def _prepare(
    col: Collection, deck: CompiledDeck, sub: Subscription
) -> tuple[CompiledDeck, frozenset[int]]:
    """The deck without notetype ids owned by other subscriptions, and those ids."""
    # Notetype ids of the other subscriptions are never reused nor adopted.
    exclude = foreign_notetype_ids(read_catalog(col), sub)
    return _without_foreign_anki_ids(deck, exclude), exclude


def preview_plan(col: Collection, deck: CompiledDeck, sub: Subscription) -> Plan:
    """The plan `update_subscription` starts from for `deck`; writes nothing."""
    prepared, exclude = _prepare(col, deck, sub)
    return _plan(col, prepared, sub, exclude)[1]


def update_subscription(
    col: Collection,
    sub: Subscription,
    *,
    transport: Transport,
    profile_dir: Path,
    confirmed_full_sync: bool,
    undo_label: str,
) -> tuple[Subscription, Plan]:
    """Fetch, plan and apply one subscription.

    deck.json is fetched again (without ETag) so the plan is computed on what is
    served now. Nothing is applied when the plan is blocked or needs an
    unconfirmed full sync; the subscription is then returned unchanged. A media
    download failure raises `SourceError` before the collection is touched.

    Media are downloaded and written first; the local state is then read again
    and the plan recomputed right before applying, so an edit the user makes
    during a long download is never overwritten. That plan still uses the
    previous media table, which tells the engine which media changed; the
    notes are written with the new local names.
    """
    fetched = fetch_deck(sub.base_url, etag=None, transport=transport)
    if fetched is None:
        raise SourceError("http_error", "unexpected 304 without ETag")
    deck, exclude = _prepare(col, fetched.deck, sub)
    base, plan = _plan(col, deck, sub, exclude)
    if _held(plan, confirmed_full_sync):
        return sub, plan

    media = sub.media
    if plan.media_to_download:
        downloads = [
            (entry, fetch_media(sub.base_url, entry, transport=transport))
            for entry in plan.media_to_download
        ]
        media = write_media(col, downloads, sub.media)
        # The download may have taken minutes: plan again on the current state.
        base, plan = _plan(col, deck, sub, exclude)
        if _held(plan, confirmed_full_sync):
            return sub, plan
    staged = replace(base, media=media, etag=fetched.etag)
    new_sub, extra = apply_plan(
        col,
        deck,
        staged,
        plan,
        undo_label=undo_label,
        confirmed_full_sync=confirmed_full_sync,
    )
    _write_versions(profile_dir, deck, new_sub)
    return new_sub, _with_extra_skipped(plan, extra)
