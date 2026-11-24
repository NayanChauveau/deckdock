"""Pure decision engine: from the received deck and the local state, an action plan.

Applies the rules of the design §5.4 (notes, tags, notetypes) and the media naming
rules of §5.5. This module imports neither `anki` nor `aqt` so it can be reused
outside Anki; the adapter reads the collection into a `LocalState` and executes
the returned `Plan`.
"""

from __future__ import annotations

import functools
import html
import os
import re
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from deckdock.format import CompiledDeck, MediaEntry, Note, Notetype

from deckdock_addon.store import MediaRecord, Received, Subscription, fingerprint

DELETED_TAG = "DeckDock::Deleted"
_PREVIEW_CHARS = 60

# Same reference patterns as `deckdock.format.check` (group 1 is the file name).
_REFERENCE_PATTERNS = (
    re.compile(r"""\bsrc\s*=\s*"([^"]*)\"""", re.IGNORECASE),
    re.compile(r"""\bsrc\s*=\s*'([^']*)'""", re.IGNORECASE),
    re.compile(r"\[sound:([^\]]*)\]"),
    re.compile(r"""\burl\(\s*["']?([^"')]*?)["']?\s*\)""", re.IGNORECASE),
)
_HTML_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f]")

NotetypeChange = Literal["create", "update", "append_fields", "unchanged"]
SkipReason = Literal[
    "modified_locally", "deleted_locally", "foreign_note", "no_base_conflict"
]


# --- inputs ---


@dataclass(frozen=True)
class LocalNote:
    """A note of the collection, with local media names in its fields."""

    note_id: int
    guid: str
    notetype_anki_id: int
    fields: dict[str, str]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class LocalNotetype:
    """A notetype of the collection.

    `templates` (name, front, back) and `css` are optional, with local media
    names; when given, a notetype whose templates and CSS already match the deck
    is reported as "unchanged" instead of "update".
    """

    anki_id: int
    field_names: tuple[str, ...]
    template_count: int
    is_cloze: bool
    templates: tuple[tuple[str, str, str], ...] | None = None
    css: str | None = None


@dataclass(frozen=True)
class LocalState:
    notes_by_guid: dict[str, LocalNote]
    notetypes: dict[int, LocalNotetype]
    root_deck_exists: bool


def received_missing_plan(deck: CompiledDeck, sub: Subscription) -> Plan:
    """Blocked plan: an installed subscription whose received fingerprints are missing.

    Planning from nothing would recreate the notes the user deleted and never
    retire anything, so nothing is planned until the file arrives.
    """
    names = {nt["id"]: nt["name"] for nt in deck["notetypes"]}
    message = "The received fingerprints of this deck are missing on this computer."
    return _blocked_plan(message, sub, names, RECEIVED_MISSING)


# --- plan ---


@dataclass(frozen=True)
class NotetypeAction:
    slug: str
    change: NotetypeChange
    anki_id: int | None
    appended_fields: tuple[str, ...]


@dataclass(frozen=True)
class NoteAction:
    """One note operation. `fields` use origin media names.

    `record` means "identical: only record the fingerprint".
    """

    kind: Literal["create", "update", "retire", "record"]
    guid: str
    note_id: int | None
    fields: dict[str, str] | None
    tags: tuple[str, ...] | None
    deck_path: str | None
    notetype_slug: str | None


@dataclass(frozen=True)
class Skipped:
    guid: str
    reason: SkipReason
    preview: str


@dataclass(frozen=True)
class Counts:
    created: int
    updated: int
    retired: int
    skipped: int
    notetypes_updated: int


@dataclass(frozen=True)
class Plan:
    blocked: str | None
    needs_full_sync_confirmation: bool
    notetype_actions: tuple[NotetypeAction, ...]
    note_actions: tuple[NoteAction, ...]
    skipped: tuple[Skipped, ...]
    media_to_download: tuple[MediaEntry, ...]
    new_received: dict[str, Received]
    counts: Counts
    # Display names of the deck's notetypes by slug, for the summary.
    notetype_names: dict[str, str] = field(default_factory=dict[str, str])
    # Why the plan is blocked when the summary has its own localized text for it.
    blocked_code: str | None = None


# The received fingerprints of an installed subscription are not on this computer
# (the media folder file has not been synced yet, or is unusable).
RECEIVED_MISSING = "received_missing"


# --- media names ---


def _is_local_reference(name: str) -> bool:
    return (
        bool(name)
        and "://" not in name
        and not name.startswith(("/", "data:"))
        and "{{" not in name
    )


def _decode(raw: str) -> str:
    return urllib.parse.unquote(html.unescape(raw))


def normalize_field(text: str) -> str:
    """Field text as Anki stores it: NFC, no "\\r", no C0 control except tab/newline."""
    return _CONTROL.sub("", unicodedata.normalize("NFC", text))


def _reference_spans(text: str) -> list[tuple[int, int]]:
    """Sorted, non-overlapping, non-empty spans of media names in `text`."""
    spans: list[tuple[int, int]] = []
    for pattern in _REFERENCE_PATTERNS:
        spans.extend(m.span(1) for m in pattern.finditer(text))
    out: list[tuple[int, int]] = []
    pos = 0
    for start, end in sorted(spans):
        if start >= pos and start != end:
            out.append((start, end))
            pos = end
    return out


def _substitute(text: str, replace: Callable[[str], str | None]) -> str:
    """Replace each media name occurrence (raw text) by `replace(raw)` unless None."""
    parts: list[str] = []
    pos = 0
    for start, end in _reference_spans(text):
        new = replace(text[start:end])
        if new is None:
            continue
        parts.append(text[pos:start])
        parts.append(new)
        pos = end
    if not parts:
        return text
    parts.append(text[pos:])
    return "".join(parts)


def _references(text: str) -> set[str]:
    """Local media names referenced in `text` (decoded, NFC)."""
    names = (
        unicodedata.normalize("NFC", _decode(text[a:b]))
        for a, b in _reference_spans(text)
    )
    return {n for n in names if _is_local_reference(n)}


def _style_encode(raw: str, text: str) -> str:
    """Encode `text` with the encodings used by `raw` (percent, then HTML)."""
    unescaped = html.unescape(raw)
    out = text
    if urllib.parse.unquote(unescaped) != unescaped:
        out = urllib.parse.quote(out, safe="/")
    if unescaped != raw:
        out = html.escape(out, quote=False)
    return out


def _split(raw: str, prefix: str, middle: str, suffix: str) -> tuple[str, str] | None:
    """Raw spellings (a, b) of `prefix` and `suffix` such that raw = a + m + b.

    The first valid split (shortest a, then shortest b) is chosen, so the same
    raw a and b are found again when mapping the rewritten name back.
    """
    n = len(raw)
    for i in range(n + 1):
        if _decode(raw[:i]) != prefix:
            continue
        for j in range(n, i - 1, -1):
            if _decode(raw[j:]) == suffix and _decode(raw[i:j]) == middle:
                return raw[:i], raw[j:]
    return None


def _encode_like(raw: str, name: str, new: str) -> str:
    """Spell `new` like `raw` spells `name`, keeping the common prefix and suffix as is.

    Anki renames a file by inserting a suffix before the extension, so the
    differing part is usually only the inserted text, and mapping back restores
    the original spelling exactly.
    """
    p = len(os.path.commonprefix([name, new]))
    limit = min(len(name), len(new)) - p
    s = len(os.path.commonprefix([name[p:][::-1], new[p:][::-1]]))
    s = min(s, limit)
    split = _split(raw, name[:p], name[p : len(name) - s], name[len(name) - s :])
    if split is not None:
        a, b = split
        out = a + _style_encode(raw, new[p : len(new) - s]) + b
        if _decode(out) == new:
            return out
    out = _style_encode(raw, new)
    return out if _decode(out) == new else new


def _rewrite(text: str, mapping: dict[str, str]) -> str:
    def replace(raw: str) -> str | None:
        name = _decode(raw)
        target = mapping.get(name) if _is_local_reference(name) else None
        if target is None or target == name:
            return None
        return _encode_like(raw, name, target)

    return _substitute(text, replace)


def to_local_names(text: str, media: dict[str, MediaRecord]) -> str:
    """Rewrite media references from origin names to local Anki names."""
    return _rewrite(text, {origin: r.local_name for origin, r in media.items()})


def _reverse(media: dict[str, MediaRecord]) -> dict[str, str]:
    reverse: dict[str, str] = {}
    for origin, r in sorted(media.items()):
        _ = reverse.setdefault(r.local_name, origin)
    return reverse


def to_origin_names(text: str, media: dict[str, MediaRecord]) -> str:
    """Rewrite media references from local Anki names back to origin names."""
    return _rewrite(text, _reverse(media))


class _Canon:
    """Comparable form of field, template and CSS text.

    Text is normalized like Anki stores it, and every recognized media
    reference becomes a token of its decoded origin name, so spelling and local
    renaming never look like an edit. On the local side, a name that is the
    origin name of a media stored under another local name stays literal: the
    user pointed it at another file.
    """

    def __init__(self, media: dict[str, MediaRecord]) -> None:
        nfc = functools.partial(unicodedata.normalize, "NFC")
        self.reverse: dict[str, str] = {
            nfc(k): nfc(v) for k, v in _reverse(media).items()
        }
        self.origins: set[str] = {nfc(k) for k in media}

    @staticmethod
    def _tokens(text: str, token: Callable[[str], str | None]) -> str:
        def replace(raw: str) -> str | None:
            name = unicodedata.normalize("NFC", _decode(raw))
            if not _is_local_reference(name):
                return None
            t = token(name)
            return None if t is None else f"\x00{t}\x00"

        return _substitute(normalize_field(text), replace)

    def deck(self, text: str) -> str:
        return self._tokens(text, lambda name: name)

    def local(self, text: str) -> str:
        def token(name: str) -> str | None:
            if name in self.reverse:
                return self.reverse[name]
            return None if name in self.origins else name

        return self._tokens(text, token)

    def deck_fields(self, fields: dict[str, str]) -> dict[str, str]:
        return {k: self.deck(v) for k, v in fields.items()}

    def local_fields(self, fields: dict[str, str]) -> dict[str, str]:
        return {k: self.local(v) for k, v in fields.items()}


def received_fingerprint(fields: dict[str, str]) -> str:
    """Fingerprint recorded for received deck fields (comparable form)."""
    return fingerprint(_Canon({}).deck_fields(fields))


# --- helpers ---


def preview(text: str) -> str:
    """First characters of a field, without HTML."""
    plain = html.unescape(_HTML_TAG.sub(" ", text))
    return _WHITESPACE.sub(" ", plain).strip()[:_PREVIEW_CHARS]


def _first_field(fields: dict[str, str], order: Iterable[str] = ()) -> str:
    for name in order:
        if name in fields:
            return fields[name]
    return next(iter(fields.values()), "")


def _merge_tags(
    local: Iterable[str], previous: Iterable[str], deck: Iterable[str]
) -> tuple[str, ...]:
    """(local − previously received) ∪ deck tags, without the retirement tag."""
    tags = (set(local) - set(previous)) | set(deck)
    tags.discard(DELETED_TAG)
    return tuple(sorted(tags))


# --- notetypes ---


def _resolve_notetype(
    nt: Notetype, sub: Subscription, local: LocalState
) -> LocalNotetype | None:
    anki_id = sub.notetype_ids.get(nt["id"])
    if anki_id is None:
        deck_anki_id = nt.get("anki_id")
        if deck_anki_id is not None and deck_anki_id in local.notetypes:
            anki_id = deck_anki_id
    return None if anki_id is None else local.notetypes.get(anki_id)


def _structure_problem(nt: Notetype, loc: LocalNotetype) -> str | None:
    if (nt["kind"] == "cloze") != loc.is_cloze:
        return "its kind (standard or cloze) changed"
    if len(nt["templates"]) != loc.template_count:
        return "a card template was added or removed"
    deck_fields = tuple(nt["fields"])
    n = len(loc.field_names)
    if len(deck_fields) < n or deck_fields[:n] != loc.field_names:
        return "a field was removed, renamed or reordered"
    return None


def _notetype_texts(nt: Notetype) -> list[str]:
    return [nt["css"], *(x for t in nt["templates"] for x in (t["front"], t["back"]))]


def _templates_match(
    nt: Notetype, loc: LocalNotetype, canon: _Canon, changed: set[str]
) -> bool:
    if loc.templates is None or loc.css is None:
        return False
    if any(_references(normalize_field(t)) & changed for t in _notetype_texts(nt)):
        return False
    local_templates = tuple(
        (name, canon.local(front), canon.local(back))
        for name, front, back in loc.templates
    )
    deck_templates = tuple(
        (t["name"], canon.deck(t["front"]), canon.deck(t["back"]))
        for t in nt["templates"]
    )
    return local_templates == deck_templates and canon.local(loc.css) == canon.deck(
        nt["css"]
    )


def _notetype_action(
    nt: Notetype, loc: LocalNotetype | None, canon: _Canon, changed: set[str]
) -> NotetypeAction:
    slug = nt["id"]
    if loc is None:
        return NotetypeAction(slug, "create", nt.get("anki_id"), ())
    appended = tuple(nt["fields"][len(loc.field_names) :])
    if appended:
        return NotetypeAction(slug, "append_fields", loc.anki_id, appended)
    change: NotetypeChange = (
        "unchanged" if _templates_match(nt, loc, canon, changed) else "update"
    )
    return NotetypeAction(slug, change, loc.anki_id, ())


def _blocked_plan(
    message: str, sub: Subscription, names: dict[str, str], code: str | None = None
) -> Plan:
    return Plan(
        blocked=message,
        blocked_code=code,
        needs_full_sync_confirmation=False,
        notetype_actions=(),
        note_actions=(),
        skipped=(),
        media_to_download=(),
        new_received=dict(sub.received),
        counts=Counts(0, 0, 0, 0, 0),
        notetype_names=names,
    )


# --- plan ---


class _Builder:
    def __init__(
        self,
        sub: Subscription,
        local: LocalState,
        mapped: dict[str, int | None],
        changed_media: set[str],
        latest: dict[str, Received],
    ) -> None:
        self.sub: Subscription = sub
        self.latest: dict[str, Received] = latest
        self.local: LocalState = local
        self.mapped: dict[str, int | None] = mapped
        self.changed_media: set[str] = changed_media
        self.canon: _Canon = _Canon(sub.media)
        self.actions: list[NoteAction] = []
        self.skipped: list[Skipped] = []
        self.received: dict[str, Received] = {}

    def note(self, n: Note, field_order: tuple[str, ...]) -> None:
        guid = n["guid"]
        prev = self.sub.received.get(guid)
        loc = self.local.notes_by_guid.get(guid)
        deck_tags = tuple(sorted(set(n["tags"])))
        deck_fields = self.canon.deck_fields(n["fields"])
        new_rec = Received(fingerprint(deck_fields), deck_tags)

        if loc is None:
            if prev is not None:
                self._skip(guid, "deleted_locally", n["fields"], field_order, prev)
                return
            self.actions.append(
                NoteAction(
                    "create",
                    guid,
                    None,
                    dict(n["fields"]),
                    _merge_tags((), (), deck_tags),
                    n["deck"],
                    n["notetype"],
                )
            )
            self.received[guid] = new_rec
            return

        local_fields = self.canon.local_fields(loc.fields)
        # A changed media gets a new local name: the fields must be rewritten.
        media_changed = any(
            _references(normalize_field(v)) & self.changed_media
            for v in n["fields"].values()
        )
        same_notetype = loc.notetype_anki_id == self.mapped.get(n["notetype"])

        if prev is not None:
            local_fp = fingerprint(local_fields)
            alt = self.latest.get(guid)
            if (
                same_notetype
                and local_fp != prev.fingerprint
                and alt is not None
                and alt.fingerprint == local_fp
            ):
                # The note holds what the received file's latest snapshot
                # recorded (applied elsewhere, while this catalog says an older
                # version): unmodified, with that entry as its base.
                prev = alt
            if not same_notetype or local_fp != prev.fingerprint:
                self._skip(guid, "modified_locally", loc.fields, (), prev)
                return
            tags_changed = set(deck_tags) != set(prev.tags) or DELETED_TAG in loc.tags
            unchanged = new_rec.fingerprint == prev.fingerprint
            if unchanged and not tags_changed and not media_changed:
                self.received[guid] = prev
                return
            self._update(n, loc, prev.tags, deck_tags)
            self.received[guid] = new_rec
            return

        if not same_notetype:
            self._skip(guid, "foreign_note", loc.fields, (), None)
            return
        if local_fields != deck_fields:
            self._skip(guid, "no_base_conflict", loc.fields, (), None)
            return
        tags = _merge_tags(loc.tags, (), deck_tags)
        if media_changed or tags != tuple(sorted(set(loc.tags))):
            self._update(n, loc, (), deck_tags)
        else:
            self.actions.append(
                NoteAction("record", guid, loc.note_id, None, None, None, None)
            )
        self.received[guid] = new_rec

    def retire(self, guid: str, prev: Received) -> None:
        # The received entry is kept: if the note comes back to the deck after
        # the user deleted it, it must not be recreated.
        self.received[guid] = prev
        loc = self.local.notes_by_guid.get(guid)
        if loc is None or DELETED_TAG in loc.tags:
            return
        tags = tuple(sorted({*loc.tags, DELETED_TAG}))
        self.actions.append(
            NoteAction("retire", guid, loc.note_id, None, tags, None, None)
        )

    def _update(
        self,
        n: Note,
        loc: LocalNote,
        previous: Iterable[str],
        deck_tags: tuple[str, ...],
    ) -> None:
        self.actions.append(
            NoteAction(
                "update",
                n["guid"],
                loc.note_id,
                dict(n["fields"]),
                _merge_tags(loc.tags, previous, deck_tags),
                None,
                n["notetype"],
            )
        )

    def _skip(
        self,
        guid: str,
        reason: SkipReason,
        fields: dict[str, str],
        order: Iterable[str],
        prev: Received | None,
    ) -> None:
        self.skipped.append(Skipped(guid, reason, preview(_first_field(fields, order))))
        if prev is not None:
            self.received[guid] = prev


def make_plan(
    deck: CompiledDeck,
    sub: Subscription,
    local: LocalState,
    latest: dict[str, Received] | None = None,
) -> Plan:
    """The plan for `deck`, from `sub.received` (the installed version's snapshot).

    `latest` is the received file's latest snapshot. A note whose fields differ
    from its installed entry but match its `latest` entry is not reported as
    modified: the catalog lags behind an apply made on another computer.
    """
    names = {nt["id"]: nt["name"] for nt in deck["notetypes"]}
    resolved = {nt["id"]: _resolve_notetype(nt, sub, local) for nt in deck["notetypes"]}

    problems = [
        f'Note type "{nt["name"]}": {problem}.'
        for nt in deck["notetypes"]
        if (loc := resolved[nt["id"]]) is not None
        and (problem := _structure_problem(nt, loc)) is not None
    ]
    if problems:
        message = (
            "Structure change not supported by this version of DeckDock. "
            + " ".join(problems)
        )
        return _blocked_plan(message, sub, names)

    media = tuple(
        m
        for m in deck["media"]
        if (r := sub.media.get(m["filename"])) is None or r.sha256 != m["sha256"]
    )
    changed = {unicodedata.normalize("NFC", m["filename"]) for m in media}
    canon = _Canon(sub.media)
    nt_actions = tuple(
        _notetype_action(nt, resolved[nt["id"]], canon, changed)
        for nt in deck["notetypes"]
    )
    mapped = {
        slug: (None if loc is None else loc.anki_id) for slug, loc in resolved.items()
    }
    field_orders = {nt["id"]: tuple(nt["fields"]) for nt in deck["notetypes"]}

    builder = _Builder(sub, local, mapped, changed, latest or {})
    deck_guids: set[str] = set()
    for n in deck["notes"]:
        deck_guids.add(n["guid"])
        builder.note(n, field_orders.get(n["notetype"], ()))
    for guid, prev in sub.received.items():
        if guid not in deck_guids:
            builder.retire(guid, prev)

    def count(kind: str) -> int:
        return sum(1 for a in builder.actions if a.kind == kind)

    return Plan(
        blocked=None,
        needs_full_sync_confirmation=any(
            a.change == "append_fields" for a in nt_actions
        ),
        notetype_actions=nt_actions,
        note_actions=tuple(builder.actions),
        skipped=tuple(builder.skipped),
        media_to_download=media,
        new_received=builder.received,
        counts=Counts(
            created=count("create"),
            updated=count("update"),
            retired=count("retire"),
            skipped=len(builder.skipped),
            notetypes_updated=sum(
                1 for a in nt_actions if a.change in ("update", "append_fields")
            ),
        ),
        notetype_names=names,
    )


# --- summary ---


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


_FR: dict[str, Callable[[int], str]] = {
    "created": lambda n: _plural(n, "nouvelle", "nouvelles"),
    "updated": lambda n: _plural(n, "mise à jour", "mises à jour"),
    "retired": lambda n: _plural(n, "retirée", "retirées"),
    "modified_locally": lambda n: _plural(
        n, "modifiée par toi (non mise à jour)", "modifiées par toi (non mises à jour)"
    ),
    "deleted_locally": lambda n: _plural(
        n, "supprimée par toi (non recréée)", "supprimées par toi (non recréées)"
    ),
    "foreign_note": lambda n: _plural(
        n,
        "déjà présente ailleurs (non touchée)",
        "déjà présentes ailleurs (non touchées)",
    ),
    "no_base_conflict": lambda n: _plural(
        n,
        "différente d'une note déjà présente (non touchée)",
        "différentes de notes déjà présentes (non touchées)",
    ),
    "notetypes": lambda n: f"notetypes : {n} mis à jour",
}

_EN: dict[str, Callable[[int], str]] = {
    "created": lambda n: f"{n} new",
    "updated": lambda n: f"{n} updated",
    "retired": lambda n: f"{n} retired",
    "modified_locally": lambda n: f"{n} modified by you (not updated)",
    "deleted_locally": lambda n: f"{n} deleted by you (not recreated)",
    "foreign_note": lambda n: f"{n} already present elsewhere (not touched)",
    "no_base_conflict": lambda n: f"{n} different from an existing note (not touched)",
    "notetypes": lambda n: f"note types: {n} updated",
}

_TEXTS = {
    "fr": {
        "nothing": "rien à changer",
        "blocked": (
            "Mise à jour refusée : changement de structure non pris en charge par "
            "cette version de DeckDock."
        ),
        RECEIVED_MISSING: (
            "Les données de suivi de ce deck ne sont pas encore arrivées sur cet "
            "ordinateur. Synchronise Anki (médias compris), puis réessaie."
        ),
        "templates": (
            "Les modèles de carte et le CSS des types de carte de ce deck sont "
            "remplacés par ceux du deck (tes modifications éventuelles sont écrasées)."
        ),
        "full_sync": (
            "Cette mise à jour ajoute un champ au type de carte {name}. Anki demandera "
            "une synchronisation complète : synchronise d'abord tes autres appareils "
            "(téléphone, tablette), puis confirme."
        ),
    },
    "en": {
        "nothing": "nothing to change",
        "blocked": (
            "Update refused: structure change not supported by this version of DeckDock."
        ),
        RECEIVED_MISSING: (
            "This deck's tracking data has not reached this computer yet. Sync Anki "
            "(including media), then try again."
        ),
        "templates": (
            "The card templates and CSS of this deck's note types are replaced by "
            "the deck's (any changes you made to them are overwritten)."
        ),
        "full_sync": (
            "This update adds a field to the note type {name}. Anki will ask for a "
            "full sync: sync your other devices (phone, tablet) first, then confirm."
        ),
    },
}

_SKIP_ORDER: tuple[SkipReason, ...] = (
    "modified_locally",
    "deleted_locally",
    "foreign_note",
    "no_base_conflict",
)


def summary_lines(plan: Plan, name: str, edition: str, lang: str) -> list[str]:
    """Summary text of a plan, in French when `lang` is "fr", else in English."""
    key = "fr" if lang == "fr" else "en"
    labels = _FR if key == "fr" else _EN
    texts = _TEXTS[key]
    title = f"{name} ({edition})"
    if plan.blocked_code is not None:
        return [f"{title} — {texts[plan.blocked_code]}"]
    if plan.blocked is not None:
        return [f"{title} — {texts['blocked']}", plan.blocked]

    c = plan.counts
    parts = [labels["created"](c.created), labels["updated"](c.updated)]
    parts.append(labels["retired"](c.retired))
    for reason in _SKIP_ORDER:
        n = sum(1 for s in plan.skipped if s.reason == reason)
        if n:
            parts.append(labels[reason](n))
    if c.notetypes_updated:
        parts.append(labels["notetypes"](c.notetypes_updated))
    has_changes = any((c.created, c.updated, c.retired, c.skipped, c.notetypes_updated))
    head = ", ".join(parts) if has_changes else texts["nothing"]
    lines = [f"{title} — {head}"]
    if c.notetypes_updated:
        lines.append(texts["templates"])
    for action in plan.notetype_actions:
        if action.change == "append_fields":
            nt_name = plan.notetype_names.get(action.slug, action.slug)
            lines.append(texts["full_sync"].format(name=nt_name))
    return lines
