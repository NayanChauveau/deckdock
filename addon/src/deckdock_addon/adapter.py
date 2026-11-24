"""Anki adapter: read the local state of a subscription and execute an engine plan.

This is the only module that writes into the user's collection. Media files are
written first, outside the collection operation, and never overwrite a file.
Every collection change of one update (notetypes, decks, notes and the persisted
subscription) is merged into a single undo entry; if a step fails, the steps
already done are undone before the error propagates.
"""

from __future__ import annotations

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
    NotetypeAction,
    Plan,
    Skipped,
    make_plan,
    preview,
    received_fingerprint,
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
    write_full_versions,
)

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
        self.pos: int | None = None

    def local(self, text: str) -> str:
        return to_local_names(text, self.sub.media)

    def merge(self) -> None:
        if self.pos is not None:
            _ = self.col.merge_undo_entries(self.pos)

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

    def apply_notetype(self, action: NotetypeAction) -> None:
        mm = self.col.models
        nt = self.notetypes[action.slug]
        if action.change == "create":
            if action.slug in self.imposed:
                return  # already created with its imposed id
            self.ids[action.slug] = int(mm.add(self._new_notetype(nt)).id)
            self.merge()
            return
        if action.anki_id is None:
            raise ValueError(f"notetype {action.slug!r} has no Anki id")
        self.ids[action.slug] = action.anki_id
        if action.change == "unchanged":
            return
        nt_dict = mm.get(NotetypeId(action.anki_id))
        if nt_dict is None:
            raise ValueError(f"notetype {action.slug!r} disappeared")
        for name in action.appended_fields:
            mm.add_field(nt_dict, mm.new_field(name))
        self._set_templates(nt_dict, nt)
        _ = mm.update_dict(nt_dict)
        self.merge()

    # decks

    def root_deck(self) -> int:
        info = self.deck["deck"]
        for did in (self.sub.root_deck_anki_id, info.get("anki_id")):
            if did is not None and _deck_exists(self.col, did):
                return did
        did = self.col.decks.id(info["name"])
        if did is None:
            raise ValueError(f"cannot create deck {info['name']!r}")
        self.merge()
        return int(did)

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

    def taken_guids(self, guids: list[str]) -> set[str]:
        taken: set[str] = set()
        for chunk in _chunks(guids):
            marks = ",".join("?" * len(chunk))
            sql = f"select guid from notes where guid in ({marks})"
            taken.update(cast(list[str], _db(self.col).list(sql, *chunk)))
        return taken

    def create_notes(self, root: int) -> list[Skipped]:
        creates = [a for a in self.plan.note_actions if a.kind == "create"]
        if not creates:
            return []
        taken = self.taken_guids([a.guid for a in creates])
        skipped = [
            Skipped(
                a.guid,
                "foreign_note",
                preview(next(iter((a.fields or {}).values()), "")),
            )
            for a in creates
            if a.guid in taken
        ]
        todo = [a for a in creates if a.guid not in taken]
        decks = self.deck_ids(root, {a.deck_path or "" for a in todo})
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
        if requests:
            _ = self.col.add_notes(requests)
            self.merge()
        return skipped

    def change_notes(self) -> None:
        changed: list[AnkiNote] = []
        for a in self.plan.note_actions:
            if a.kind not in ("update", "retire") or a.note_id is None:
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

    def persist(self, sub: Subscription) -> None:
        """Store the subscription in the collection config, inside the undo entry.

        Undoing the update then also restores what the subscription had received,
        so undone notes are not later mistaken for notes deleted by the user.
        """
        catalog = read_catalog(self.col)
        if any(s.id == sub.id for s in catalog.subscriptions):
            subs = tuple(sub if s.id == sub.id else s for s in catalog.subscriptions)
        else:
            subs = (*catalog.subscriptions, sub)
        _ = self.col.set_config(CONFIG_KEY, dump_catalog(Catalog(subs)), undoable=True)
        self.merge()

    def run(self, undo_label: str) -> tuple[Subscription, tuple[Skipped, ...]]:
        self.create_with_imposed_ids()
        self.pos = self.col.add_custom_undo_entry(undo_label)
        try:
            for action in self.plan.notetype_actions:
                self.apply_notetype(action)
            root = self.root_deck()
            extra = self.create_notes(root)
            self.change_notes()
            received = dict(self.plan.new_received)
            for s in extra:
                _ = received.pop(s.guid, None)
            new_sub = replace(
                self.sub,
                installed_version=self.deck["deck"]["version"],
                available_version=None,
                notetype_ids=self.ids,
                root_deck_anki_id=root,
                received=received,
            )
            self.persist(new_sub)
        except BaseException:
            self.rollback(undo_label)
            raise
        return new_sub, tuple(extra)

    def rollback(self, undo_label: str) -> None:
        """Undo the steps already applied (best effort; the original error wins)."""
        try:
            self.merge()
            if self.col.undo_status().undo == undo_label:
                _ = self.col.undo()
        except Exception:  # noqa: BLE001, S110
            pass


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
    """
    if plan.blocked is not None:
        raise ValueError(f"refusing to apply a blocked plan: {plan.blocked}")
    if plan.needs_full_sync_confirmation and not confirmed_full_sync:
        raise ValueError("this plan needs the user to confirm a full sync")
    return _Applier(col, deck, sub, plan).run(undo_label)


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
    """
    fetched = fetch_deck(sub.base_url, etag=None, transport=transport)
    if fetched is None:
        raise SourceError("http_error", "unexpected 304 without ETag")
    deck = fetched.deck
    plan = make_plan(deck, sub, read_local_state(col, deck, sub))
    if plan.blocked is not None or (
        plan.needs_full_sync_confirmation and not confirmed_full_sync
    ):
        return sub, plan

    downloads = [
        (entry, fetch_media(sub.base_url, entry, transport=transport))
        for entry in plan.media_to_download
    ]
    staged = replace(
        sub, media=write_media(col, downloads, sub.media), etag=fetched.etag
    )
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
