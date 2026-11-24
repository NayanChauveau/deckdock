"""DeckDock window, add dialog and summary dialog (Tools > DeckDock).

Anything that is not Qt (which subscriptions are due, how a check result is
recorded, the summary text of a plan) lives in small pure functions at the top,
which have tests. The Qt part follows one rule: the catalog (synced collection
config plus the local check state file) is read and written on the main thread; background work (network, collection reads, the apply
operation) returns plain values. A counter, `_epoch`, is incremented when the
profile closes, so a callback from before that moment does nothing.
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, final, override

from anki.collection import Collection, OpChanges
from aqt import dialogs, gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QAbstractItemView,
    QAction,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    qconnect,  # pyright: ignore[reportUnknownVariableType]
)
from aqt.utils import (
    askUser,  # pyright: ignore[reportUnknownVariableType]
    openLink,
    showInfo,
    showWarning,
    tooltip,
)

from deckdock_addon import strings
from deckdock_addon.adapter import (
    RECEIVED_WRITE_FAILED,
    ApplyRefusedError,
    Download,
    PartialApplyError,
    apply_download,
    browser_search,
    download_update,
    preview_plan,
)
from deckdock_addon.engine import Plan, Skipped, summary_lines
from deckdock_addon.sources import (
    FetchedDeck,
    IndexEdition,
    Response,
    Source,
    SourceError,
    Transport,
    edition_base_url,
    fetch_deck,
    fetch_index,
    parse_source,
    urllib_transport,
)
from deckdock_addon.store import (
    Catalog,
    ConflictingEdition,
    DuplicateSubscription,
    Subscription,
    add,
    check_is_due,
    check_state_path,
    full_versions_path,
    read_catalog,
    read_check_state,
    remove,
    same_synced,
    with_check_state,
    write_catalog,
    write_check_state,
)
from deckdock_addon.store import (
    replace as replace_subscription,
)

DEFAULT_INTERVAL_HOURS = 24
STARTUP_DELAY_MS = 1500


# --- pure helpers (tested without Qt) -------------------------------------------


@dataclass(frozen=True)
class Review:
    """What an update of one subscription would do, or why it cannot be computed."""

    sub: Subscription
    plan: Plan | None
    error: str | None

    @property
    def applicable(self) -> bool:
        return self.plan is not None and self.plan.blocked is None

    @property
    def needs_full_sync(self) -> bool:
        return self.applicable and (
            self.plan is not None and self.plan.needs_full_sync_confirmation
        )


CheckOutcome = FetchedDeck | SourceError | None


def check_interval_hours(config: object) -> int:
    if isinstance(config, dict):
        value = cast("dict[str, object]", config).get("check_interval_hours")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return DEFAULT_INTERVAL_HOURS


def due_subscriptions(
    subs: Sequence[Subscription], now: datetime, interval_hours: int
) -> list[Subscription]:
    due: list[Subscription] = []
    for sub in subs:
        try:
            if check_is_due(sub.last_checked_at, now, interval_hours):
                due.append(sub)
        except ValueError:  # corrupt timestamp: check it again
            due.append(sub)
    return due


def pending_updates(subs: Sequence[Subscription]) -> list[Subscription]:
    return [s for s in subs if strings.has_update(s)]


def apply_check(
    sub: Subscription, outcome: CheckOutcome, checked_at: str
) -> Subscription:
    """Record the result of a check; nothing is applied to the collection.

    A failed write of the received file stays shown until an apply succeeds:
    a check cannot fix it, and it blocks the next updates.
    """
    sticky = sub.last_error if sub.last_error == RECEIVED_WRITE_FAILED else None
    if isinstance(outcome, SourceError):
        return replace(sub, last_error=sticky or outcome.code)
    if outcome is None:  # HTTP 304: the ETag still matches
        return replace(sub, last_error=sticky, last_checked_at=checked_at)
    return replace(
        sub,
        etag=outcome.etag,
        last_error=sticky,
        last_checked_at=checked_at,
        available_version=outcome.deck["deck"]["version"],
    )


def record_apply(
    sub: Subscription, applied: Subscription, checked_at: str
) -> Subscription:
    """The local check state after a successful apply of `applied`.

    The version just applied is the version seen on the server, so undoing the
    apply shows the update as available again. `applied.last_error` reports a
    received file that could not be written.
    """
    return replace(
        sub,
        etag=applied.etag,
        available_version=applied.installed_version,
        last_error=applied.last_error,
        last_checked_at=checked_at,
    )


def new_subscription(
    source: Source, base_url: str, fetched: FetchedDeck, sub_id: str
) -> Subscription:
    info = fetched.deck["deck"]
    return Subscription(
        id=sub_id,
        source_url=source.url,
        base_url=base_url,
        deck_id=info["id"],
        edition=info["edition"],
        name=info["name"],
        etag=fetched.etag,
        available_version=info["version"],
        last_checked_at=_now(),
    )


def browsable_guid(skipped: Skipped) -> str | None:
    """The GUID to look up in the Browser, or None for a note the user deleted."""
    return None if skipped.reason == "deleted_locally" else skipped.guid


def clears_undo(plan: Plan) -> bool:
    """Creating a notetype with a declared `anki_id` clears Anki's undo history."""
    return any(
        a.change == "create" and a.anki_id is not None for a in plan.notetype_actions
    )


def section_lines(review: Review, lang: str) -> list[str]:
    sub = review.sub
    if review.plan is None:
        reason = strings.error_text(review.error, lang)
        return [f"{sub.name} ({sub.edition}) — {reason}"]
    lines = summary_lines(review.plan, sub.name, sub.edition, lang)
    if review.plan.blocked is None and clears_undo(review.plan):
        lines.append(strings.text("CLEARS_UNDO", lang))
    return lines


def exception_message(exc: Exception, lang: str | None = None) -> str:
    """Localized text for a known error code, else the exception type and message."""
    if isinstance(exc, SourceError | ApplyRefusedError | PartialApplyError):
        return strings.error_text(exc.code, lang)
    detail = f"{type(exc).__name__}: {exc}"
    return strings.text("ERROR_DETAIL", lang).format(detail=detail)


def failure_message(sub: Subscription, exc: Exception, lang: str) -> str:
    """Why the apply of `sub` failed, for the report shown after the last one."""
    return f"{sub.name} ({sub.edition}) — {exception_message(exc, lang)}"


def apply_changes() -> OpChanges:
    """What an apply may change: notes, cards, decks, notetypes, tags and config."""
    return OpChanges(
        card=True,
        note=True,
        deck=True,
        tag=True,
        notetype=True,
        config=True,
        browser_table=True,
        browser_sidebar=True,
        note_text=True,
        study_queues=True,
    )


def held_message(
    sub: Subscription, plan: Plan, confirmed: bool, lang: str
) -> str | None:
    """Why `update_subscription` applied nothing, or None when it was applied."""
    if plan.blocked is not None:
        return "\n".join(summary_lines(plan, sub.name, sub.edition, lang))
    if plan.needs_full_sync_confirmation and not confirmed:
        title = f"{sub.name} ({sub.edition}) — "
        return title + strings.text("CHANGED_SINCE_SUMMARY", lang)
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --- state ----------------------------------------------------------------------

_dialog: ManagerDialog | None = None
_modals: list[QDialog] = []
_startup_started = False
_busy = False
_epoch = 0


def _info(text: str, *, parent: QWidget, title: str) -> None:
    _ = showInfo(text, parent=parent, title=title)


def _warn(text: str, *, parent: QWidget, title: str) -> None:
    _ = showWarning(text, parent=parent, title=title)


def _main() -> object:
    return mw


def _parent() -> QWidget:
    return mw


def _collection() -> Collection | None:
    main = cast("object | None", mw)
    return None if main is None else mw.col


def _stale(epoch: int, collection: Collection | None) -> bool:
    return _epoch != epoch or _collection() is not collection or collection is None


def _transport(epoch: int) -> Transport:
    """The HTTPS transport, refusing to start a request once the profile closed."""

    def transport(url: str, headers: dict[str, str], max_bytes: int) -> Response:
        if _epoch != epoch:
            raise SourceError("cancelled")
        return urllib_transport(url, headers, max_bytes)

    return transport


def _profile_dir() -> Path:
    return Path(mw.pm.profileFolder())


def _interval_hours() -> int:
    config = mw.addonManager.getConfig(mw.addonManager.addonFromModule(__name__))
    return check_interval_hours(config)


def _state_path() -> Path:
    return check_state_path(_profile_dir())


def _read_catalog() -> Catalog | None:
    """The catalog with the local check state, or None.

    None when no profile is open or the stored catalog is unreadable.
    """
    col = _collection()
    if col is None:
        return None
    try:
        catalog = read_catalog(col)
    except ValueError:
        return None
    return with_check_state(catalog, read_check_state(_state_path()))


def _save(col: Collection, before: Catalog, after: Catalog) -> None:
    """Store `after`: the check state locally, the collection config only if changed.

    A check only changes the local state, so it never rewrites the synced
    catalog (config sync keeps the newest value of the whole key).
    """
    if not same_synced(before, after):
        write_catalog(col, after)
    try:
        write_check_state(_state_path(), after)
    except OSError:
        traceback.print_exc()  # only a cache of the last check


def _update_catalog(change: Callable[[Catalog], Catalog]) -> bool:
    col = _collection()
    catalog = _read_catalog()
    if col is None or catalog is None:
        return False
    _save(col, catalog, change(catalog))
    return True


def _update_subscription(
    sub_id: str, change: Callable[[Subscription], Subscription]
) -> None:
    def apply(catalog: Catalog) -> Catalog:
        for sub in catalog.subscriptions:
            if sub.id == sub_id:
                return replace_subscription(catalog, change(sub))
        return catalog

    _ = _update_catalog(apply)


def _set_busy(busy: bool) -> None:
    global _busy
    _busy = busy
    if _dialog is not None:
        _dialog.update_buttons()


def _track(dialog: QDialog) -> None:
    _modals.append(dialog)

    def on_finished(_result: int) -> None:
        _forget(dialog)

    qconnect(dialog.finished, on_finished)


def _forget(dialog: QDialog) -> None:
    if dialog in _modals:
        _modals.remove(dialog)


# --- hooks ----------------------------------------------------------------------


def register() -> None:
    gui_hooks.main_window_did_init.append(_add_menu)
    gui_hooks.profile_did_open.append(_schedule_startup)
    gui_hooks.profile_will_close.append(_close_profile)


def _add_menu() -> None:
    action = QAction(strings.MENU, mw)
    qconnect(action.triggered, open_manager)
    mw.form.menuTools.addAction(action)


def open_manager(*_args: object) -> None:
    global _dialog
    if _collection() is None:
        _info(strings.NO_PROFILE, parent=_parent(), title=strings.WINDOW_TITLE)
        return
    if _dialog is None:
        _dialog = ManagerDialog(_parent())
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    _dialog.refresh()


def _close_profile() -> None:
    global _startup_started, _epoch, _dialog
    _startup_started = False
    _epoch += 1
    _set_busy(False)
    for modal in _modals.copy():
        modal.reject()
    if _dialog is not None:
        _dialog.deleteLater()
        _ = _dialog.close()
        _dialog = None


def _schedule_startup() -> None:
    # profile_did_open runs while the main window is still settling.
    QTimer.singleShot(STARTUP_DELAY_MS, _startup_check)


# --- check ----------------------------------------------------------------------


def _check_one(sub: Subscription, transport: Transport) -> CheckOutcome:
    try:
        return fetch_deck(sub.base_url, etag=sub.etag, transport=transport)
    except SourceError as exc:
        return exc


def _run_check(
    subs: list[Subscription], on_done: Callable[[], None], *, progress: bool
) -> None:
    """Fetch deck.json of each subscription in the background; apply nothing."""
    collection = _collection()
    epoch = _epoch
    if _busy or collection is None or not subs:
        return
    transport = _transport(epoch)
    _set_busy(True)

    def op(_col: Collection) -> list[tuple[str, CheckOutcome]]:
        return [(s.id, _check_one(s, transport)) for s in subs]

    def success(results: list[tuple[str, CheckOutcome]]) -> None:
        if _stale(epoch, collection):
            return
        checked_at = _now()
        by_id = dict(results)

        def merge(catalog: Catalog) -> Catalog:
            out = catalog
            for sub in catalog.subscriptions:
                if sub.id in by_id:
                    out = replace_subscription(
                        out, apply_check(sub, by_id[sub.id], checked_at)
                    )
            return out

        _ = _update_catalog(merge)
        _set_busy(False)
        if _dialog is not None:
            _dialog.refresh()
        on_done()

    def failure(exc: Exception) -> None:
        if _stale(epoch, collection):
            return
        _set_busy(False)
        _warn_exception(exc)

    query = QueryOp(parent=_parent(), op=op, success=_guarded(success)).failure(failure)
    query = query.without_collection()
    if progress:
        query = query.with_progress()
    query.run_in_background()


def _startup_check() -> None:
    global _startup_started
    collection = _collection()
    if _startup_started or _busy or collection is None:
        return
    _startup_started = True
    catalog = _read_catalog()
    if catalog is None:
        return
    due = due_subscriptions(catalog.subscriptions, datetime.now(UTC), _interval_hours())
    if due:
        _run_check(due, _offer_updates, progress=False)
    else:
        _offer_updates()


def _offer_updates() -> None:
    catalog = _read_catalog()
    if catalog is None:
        return
    pending = pending_updates(catalog.subscriptions)
    if pending:
        _start_review(pending, progress=False)


# --- review and apply -----------------------------------------------------------


Fetched = tuple[Subscription, FetchedDeck | str]


def _fetch_for_review(sub: Subscription, transport: Transport) -> Fetched:
    """Download deck.json (no collection needed); an error becomes its code."""
    try:
        fetched = fetch_deck(sub.base_url, etag=None, transport=transport)
    except SourceError as exc:
        return sub, exc.code
    return sub, ("http_error" if fetched is None else fetched)


def _plan_review(col: Collection, item: Fetched) -> Review:
    sub, fetched = item
    if isinstance(fetched, str):
        return Review(sub, None, fetched)
    return Review(sub, preview_plan(col, fetched.deck, sub), None)


def _start_review(
    subs: list[Subscription], *, progress: bool, install: bool = False
) -> None:
    """Fetch, then plan in the background, show the summary, then apply."""
    collection = _collection()
    epoch = _epoch
    if _busy or collection is None or not subs:
        return
    transport = _transport(epoch)
    _set_busy(True)

    def fail(exc: Exception) -> None:
        if _stale(epoch, collection):
            return
        _set_busy(False)
        _warn_exception(exc)

    def show(reviews: list[Review]) -> None:
        if _stale(epoch, collection):
            return
        # Above the Manager when it is open, not behind it (a macOS sheet).
        dialog = SummaryDialog(_dialog or _parent(), reviews, install=install)
        _track(dialog)

        def finished(result: int) -> None:
            if _stale(epoch, collection):
                return
            accepted = result == QDialog.DialogCode.Accepted.value
            todo = [r for r in reviews if r.applicable]
            if accepted and todo:
                _apply_next(todo, collection, epoch, [])
            else:
                _set_busy(False)

        # open() instead of exec(): no nested event loop inside a QueryOp callback.
        qconnect(dialog.finished, _guarded(finished))
        dialog.open()

    def planned(fetched: list[Fetched]) -> None:
        if _stale(epoch, collection):
            return
        QueryOp(
            parent=_parent(),
            op=lambda col: [_plan_review(col, item) for item in fetched],
            success=_guarded(show),
        ).failure(fail).run_in_background()

    # The network part runs without the collection, so Anki is not blocked on it.
    query = QueryOp(
        parent=_parent(),
        op=lambda _col: [_fetch_for_review(s, transport) for s in subs],
        success=_guarded(planned),
    ).failure(fail)
    query = query.without_collection()
    if progress:
        query = query.with_progress()
    query.run_in_background()


@dataclass
class _Applied:
    sub: Subscription
    plan: Plan
    changes: OpChanges


def _apply_next(
    todo: list[Review], collection: Collection, epoch: int, held: list[str]
) -> None:
    """Apply the reviews one after the other; stays busy until the last one.

    A subscription held back at apply time (the deck changed since the summary)
    or whose apply failed is reported at the end, and the others still go ahead.
    """
    if not todo:
        _set_busy(False)
        if _dialog is not None:
            _dialog.refresh()
        if held:
            _warn_later("\n\n".join(held))
        return
    review, rest = todo[0], todo[1:]
    sub = review.sub
    confirmed = review.needs_full_sync
    transport = _transport(epoch)
    profile_dir = _profile_dir()
    label = strings.undo_label(sub.name)

    def apply(col: Collection, download: Download) -> _Applied:
        new_sub, plan = apply_download(
            col,
            sub,
            download,
            profile_dir=profile_dir,
            confirmed_full_sync=confirmed,
            undo_label=label,
        )
        return _Applied(new_sub, plan, apply_changes())

    def success(result: _Applied) -> None:
        if _stale(epoch, collection):
            return
        message = held_message(sub, result.plan, confirmed, strings.language())
        if message is not None:
            held.append(message)
        else:
            checked_at = _now()
            _update_subscription(
                sub.id, lambda s: record_apply(s, result.sub, checked_at)
            )
            tooltip(strings.text("UPDATED").format(name=sub.name), parent=_parent())
        _apply_next(rest, collection, epoch, held)

    def failure(exc: Exception) -> None:
        if _stale(epoch, collection):
            return
        _report_exception(exc)
        if isinstance(exc, SourceError):
            code = exc.code
            _update_subscription(sub.id, lambda s: replace(s, last_error=code))
        held.append(failure_message(sub, exc, strings.language()))
        _apply_next(rest, collection, epoch, held)

    def downloaded(download: Download) -> None:
        if _stale(epoch, collection):
            return
        CollectionOp(parent=_parent(), op=lambda col: apply(col, download)).success(
            _guarded(success)
        ).failure(_guarded(failure)).run_in_background()

    # The network runs without the collection, so Anki stays usable meanwhile;
    # the plan, the media files and the changes follow in one CollectionOp.
    QueryOp(
        parent=_parent(),
        op=lambda _col: download_update(sub, transport=transport),
        success=_guarded(downloaded),
    ).failure(
        _guarded(failure)
    ).without_collection().with_progress().run_in_background()


def _warn_later(text: str) -> None:
    """Show a warning once the current callback has returned.

    Op callbacks must not open a nested event loop (`showWarning` runs
    `exec()`): Anki would wait for the warning to close before refreshing the
    interface and the undo menu.
    """
    epoch = _epoch

    def show() -> None:
        if _epoch == epoch:
            _warn(text, parent=_dialog or _parent(), title=strings.WINDOW_TITLE)

    QTimer.singleShot(0, show)


def _report_exception(exc: Exception) -> None:
    if not isinstance(exc, SourceError | ApplyRefusedError | PartialApplyError):
        # An unexpected error: keep the traceback in Anki's console/log.
        traceback.print_exception(exc)


def _warn_exception(exc: Exception) -> None:
    _report_exception(exc)
    _warn_later(exception_message(exc))


def _guarded[T](callback: Callable[[T], None]) -> Callable[[T], None]:
    """`callback`, but an exception it raises ends the busy state and is shown.

    Without this, a failing callback would leave every button disabled until
    the profile is reopened.
    """

    def run(value: T) -> None:
        try:
            callback(value)
        except Exception as exc:  # noqa: BLE001 - shown to the user, then dropped
            _set_busy(False)
            _warn_exception(exc)

    return run


# --- dialogs --------------------------------------------------------------------


@final
class ManagerDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.WINDOW_TITLE)
        self.resize(820, 420)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                strings.COLUMN_DECK,
                strings.COLUMN_EDITION,
                strings.COLUMN_VERSION,
                strings.COLUMN_STATUS,
            ]
        )
        vertical = self.table.verticalHeader()
        if vertical is not None:
            vertical.hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setStretchLastSection(True)
        self.empty = QLabel(strings.EMPTY)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)

        self.add_button = QPushButton(strings.ADD)
        self.check_button = QPushButton(strings.CHECK)
        self.apply_button = QPushButton(strings.APPLY)
        self.open_button = QPushButton(strings.OPEN_SOURCE)
        self.remove_button = QPushButton(strings.REMOVE)
        qconnect(self.add_button.clicked, self._add)
        qconnect(self.check_button.clicked, self._check)
        qconnect(self.apply_button.clicked, self._apply)
        qconnect(self.open_button.clicked, self._open_source)
        qconnect(self.remove_button.clicked, self._remove)

        buttons = QVBoxLayout()
        for button in self._buttons():
            buttons.addWidget(button)
        buttons.addStretch()
        content = QVBoxLayout()
        content.addWidget(self.table)
        content.addWidget(self.empty)
        layout = QHBoxLayout(self)
        layout.addLayout(content, 1)
        layout.addLayout(buttons)
        self.refresh()

    def _buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.add_button,
            self.check_button,
            self.apply_button,
            self.open_button,
            self.remove_button,
        )

    def update_buttons(self) -> None:
        enabled = not _busy and _read_catalog() is not None
        for button in (
            self.add_button,
            self.check_button,
            self.apply_button,
            self.remove_button,
        ):
            button.setEnabled(enabled)

    def refresh(self) -> None:
        catalog = _read_catalog()
        selected = set(self._selected_ids())
        subs = () if catalog is None else catalog.subscriptions
        self.table.setRowCount(len(subs))
        for row, sub in enumerate(subs):
            values = (
                sub.name,
                sub.edition,
                strings.version_text(sub),
                strings.status_text(sub),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, sub.id)
                self.table.setItem(row, column, item)
            if sub.id in selected:
                self.table.selectRow(row)
        self.empty.setText(
            strings.EMPTY if catalog is not None else strings.CATALOG_ERROR
        )
        self.empty.setVisible(not subs)
        self.update_buttons()

    def _add(self) -> None:
        if _busy or _collection() is None:
            return
        epoch, collection = _epoch, _collection()
        dialog = AddDialog(self)
        _track(dialog)
        _set_busy(True)  # no startup review or check while the dialog is open
        accepted = dialog.exec()
        if _stale(epoch, collection):
            return
        _set_busy(False)
        if accepted and dialog.added is not None:
            self.refresh()
            _start_review([dialog.added], progress=True, install=True)

    def _check(self) -> None:
        subs = self._targets()
        _run_check(subs, lambda: None, progress=True)

    def _apply(self) -> None:
        subs = [
            s
            for s in self._targets()
            if strings.has_update(s) or s.installed_version is None
        ]
        if not subs:
            _info(strings.NOTHING_TO_APPLY, parent=self, title=strings.WINDOW_TITLE)
            return
        _start_review(subs, progress=True)

    def _open_source(self) -> None:
        sub = self._one_selected()
        if sub is not None:
            openLink(sub.source_url)

    def _remove(self) -> None:
        if _busy:
            return
        chosen = self._selected_subscriptions()
        if not chosen:
            _info(strings.NO_SELECTION, parent=self, title=strings.WINDOW_TITLE)
            return
        # The Anki deck and its notes stay. Only the subscription goes away.
        if not askUser(
            strings.removal_message([s.name for s in chosen]),
            parent=self,
            defaultno=True,
            title=strings.WINDOW_TITLE,
        ):
            return
        ids = {s.id for s in chosen}

        def drop(catalog: Catalog) -> Catalog:
            out = catalog
            for sub_id in ids:
                out = remove(out, sub_id)
            return out

        if _update_catalog(drop):
            for sub_id in ids:
                try:
                    full_versions_path(_profile_dir(), sub_id).unlink(missing_ok=True)
                except OSError:
                    pass  # only a cache for a future comparison
        self.refresh()

    def _selected_ids(self) -> list[str]:
        rows = sorted({item.row() for item in self.table.selectedItems()})
        ids: list[str] = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                value = cast(object, item.data(Qt.ItemDataRole.UserRole))
                if isinstance(value, str):
                    ids.append(value)
        return ids

    def _selected_subscriptions(self) -> list[Subscription]:
        catalog = _read_catalog()
        if catalog is None:
            return []
        ids = set(self._selected_ids())
        return [s for s in catalog.subscriptions if s.id in ids]

    def _targets(self) -> list[Subscription]:
        """The selected subscriptions, or all of them when none is selected."""
        chosen = self._selected_subscriptions()
        if chosen:
            return chosen
        catalog = _read_catalog()
        return [] if catalog is None else list(catalog.subscriptions)

    def _one_selected(self) -> Subscription | None:
        chosen = self._selected_subscriptions()
        if len(chosen) != 1:
            _info(strings.NO_SELECTION, parent=self, title=strings.WINDOW_TITLE)
            return None
        return chosen[0]


@final
class SummaryDialog(QDialog):
    """One section per subscription: summary text, skipped notes, open in browser."""

    def __init__(
        self, parent: QWidget, reviews: list[Review], *, install: bool = False
    ) -> None:
        super().__init__(parent)
        self._lists: list[tuple[QListWidget, Review]] = []
        lang = strings.language()
        self.setWindowTitle(
            strings.text("SUMMARY_TITLE_INSTALL" if install else "SUMMARY_TITLE")
        )
        self.resize(640, 480)
        body = QWidget()
        sections = QVBoxLayout(body)
        for review in reviews:
            sections.addWidget(self._section(review, lang))
        sections.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if any(r.applicable for r in reviews):
            later = QPushButton(strings.LATER)
            confirm = any(r.needs_full_sync for r in reviews)
            apply = QPushButton(strings.CONFIRM_APPLY if confirm else strings.APPLY)
            apply.setDefault(not confirm)
            qconnect(later.clicked, self.reject)
            qconnect(apply.clicked, self.accept)
            buttons.addWidget(later)
            buttons.addWidget(apply)
        else:
            ok = QPushButton(strings.OK)
            ok.setDefault(True)
            qconnect(ok.clicked, self.reject)
            buttons.addWidget(ok)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addLayout(buttons)

    def _section(self, review: Review, lang: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        text = QLabel("\n".join(section_lines(review, lang)))
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(text)
        plan = review.plan
        if plan is not None and plan.blocked is None and plan.skipped:
            toggle = QToolButton()
            toggle.setText(
                strings.text("SKIPPED_TOGGLE").format(count=len(plan.skipped))
            )
            toggle.setCheckable(True)
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setArrowType(Qt.ArrowType.RightArrow)
            skipped = QListWidget()
            skipped.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            for note in plan.skipped:
                label = f"{note.preview} — {strings.skip_text(note.reason)}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, browsable_guid(note))
                skipped.addItem(item)
            browse = QPushButton(strings.OPEN_IN_BROWSER)
            # Notes deleted by the user have nothing to show in the Browser.
            browsable = any(browsable_guid(n) is not None for n in plan.skipped)
            skipped.setVisible(False)
            browse.setVisible(False)

            def toggled(checked: bool) -> None:
                toggle.setArrowType(
                    Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
                )
                skipped.setVisible(checked)
                browse.setVisible(checked and browsable)

            qconnect(toggle.toggled, toggled)
            qconnect(browse.clicked, lambda: self._open_in_browser(skipped))
            layout.addWidget(toggle)
            layout.addWidget(skipped)
            layout.addWidget(browse)
            self._lists.append((skipped, review))
        return box

    def _open_in_browser(self, skipped: QListWidget) -> None:
        items = skipped.selectedItems() or [
            skipped.item(i) for i in range(skipped.count())
        ]
        guids: list[str] = []
        for item in items:
            value = cast(object, item.data(Qt.ItemDataRole.UserRole)) if item else None
            if isinstance(value, str):
                guids.append(value)
        col = _collection()
        if not guids or col is None:
            return
        # Resolved at click time: the notes may have changed since the summary.
        search = browser_search(col, guids)
        if search is not None:
            dialogs.open("Browser", _main(), search=(search,))


@final
class AddDialog(QDialog):
    """Paste a URL; for a GitHub repository pick an edition; then subscribe."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.added: Subscription | None = None
        self._epoch = _epoch
        self._collection = _collection()
        self._source: Source | None = None
        self._closed = False
        self.setWindowTitle(strings.ADD_TITLE)
        self.resize(560, 260)
        help_label = QLabel(strings.ADD_HELP)
        help_label.setWordWrap(True)
        self.url = QLineEdit()
        self.url.setPlaceholderText(strings.ADD_PLACEHOLDER)
        self.pick = QLabel(strings.PICK_EDITION)
        self.editions = QListWidget()
        self.pick.setVisible(False)
        self.editions.setVisible(False)
        self.primary = QPushButton(strings.CONTINUE)
        self.primary.setDefault(True)
        cancel = QPushButton(strings.CANCEL)
        qconnect(self.primary.clicked, self._on_primary)
        qconnect(cancel.clicked, self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.primary)
        layout = QVBoxLayout(self)
        layout.addWidget(help_label)
        layout.addWidget(self.url)
        layout.addWidget(self.pick)
        layout.addWidget(self.editions)
        layout.addLayout(buttons)

    @override
    def done(self, a0: int) -> None:
        # A background fetch that ends after Cancel must change nothing.
        self._closed = True
        super().done(a0)

    def _stale(self) -> bool:
        return self._closed or _stale(self._epoch, self._collection)

    def _fail(self, message: str) -> None:
        self.primary.setEnabled(True)
        _warn(message, parent=self, title=strings.ADD_TITLE)

    def _on_primary(self) -> None:
        if self._source is None:
            self._lookup()
        else:
            self._choose_edition()

    def _run[T](self, op: Callable[[], T], success: Callable[[T], None]) -> None:
        self.primary.setEnabled(False)

        def done(result: T) -> None:
            if self._stale():
                return
            success(result)

        def failed(exc: Exception) -> None:
            if self._stale():
                return
            if not isinstance(exc, SourceError):
                traceback.print_exception(exc)
            self._fail(exception_message(exc))

        QueryOp(parent=self, op=lambda _col: op(), success=done).failure(
            failed
        ).without_collection().run_in_background()

    def _lookup(self) -> None:
        try:
            source = parse_source(self.url.text())
        except SourceError as exc:
            self._fail(strings.error_text(exc.code))
            return
        transport = _transport(self._epoch)
        if source.kind == "github":

            def got_index(editions: list[IndexEdition]) -> None:
                if not editions:
                    self._fail(strings.NO_EDITIONS)
                    return
                self._source = source
                self.editions.clear()
                for e in editions:
                    label = strings.text("EDITION_ITEM").format(
                        name=e.name,
                        edition=e.edition,
                        language=", ".join(e.language),
                        version=e.version,
                    )
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, e.edition)
                    self.editions.addItem(item)
                self.editions.setCurrentRow(0)
                self.url.setEnabled(False)
                self.pick.setVisible(True)
                self.editions.setVisible(True)
                self.primary.setText(strings.ADD)
                self.primary.setEnabled(True)

            self._run(lambda: fetch_index(source, transport=transport), got_index)
        else:
            self._fetch_and_add(source, source.url)

    def _choose_edition(self) -> None:
        item = self.editions.currentItem()
        source = self._source
        if item is None or source is None:
            return
        edition = cast(object, item.data(Qt.ItemDataRole.UserRole))
        if isinstance(edition, str):
            self._fetch_and_add(source, edition_base_url(source, edition))

    def _fetch_and_add(self, source: Source, base_url: str) -> None:
        transport = _transport(self._epoch)

        def fetch() -> FetchedDeck:
            fetched = fetch_deck(base_url, etag=None, transport=transport)
            if fetched is None:
                raise SourceError("http_error", "unexpected 304 without ETag")
            return fetched

        def got(fetched: FetchedDeck) -> None:
            sub = new_subscription(source, base_url, fetched, uuid.uuid4().hex)
            catalog = _read_catalog()
            if catalog is None:
                self._fail(strings.CATALOG_ERROR)
                return
            try:
                updated = add(catalog, sub)
            except DuplicateSubscription:
                self._fail(strings.DUPLICATE)
                return
            except ConflictingEdition:
                self._fail(strings.CONFLICTING_EDITION)
                return
            if self._collection is not None:
                _save(self._collection, catalog, updated)
            self.added = sub
            self.accept()

        self._run(fetch, got)
