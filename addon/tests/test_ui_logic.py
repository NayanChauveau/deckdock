"""The pure (non-Qt) helpers of ui.py."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from deckdock.format import CompiledDeck

from deckdock_addon import engine, ui
from deckdock_addon.sources import FetchedDeck, SourceError, parse_source
from deckdock_addon.store import Subscription
from tests.conftest import build_deck

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _sub(**overrides: object) -> Subscription:
    data: dict[str, object] = {
        "id": "s1",
        "source_url": "https://github.com/o/r",
        "base_url": "https://example.test/en/",
        "deck_id": "hello-world",
        "edition": "en",
        "name": "Hello World",
    }
    data.update(overrides)
    return Subscription(**data)  # pyright: ignore[reportArgumentType]


def _plan(deck: CompiledDeck, sub: Subscription) -> engine.Plan:
    return engine.make_plan(deck, sub, engine.LocalState({}, {}, False))


def test_due_subscriptions() -> None:
    fresh = _sub(id="a", last_checked_at=(NOW - timedelta(hours=1)).isoformat())
    stale = _sub(id="b", last_checked_at=(NOW - timedelta(hours=25)).isoformat())
    never = _sub(id="c")
    corrupt = _sub(id="d", last_checked_at="not a date")
    due = ui.due_subscriptions([fresh, stale, never, corrupt], NOW, 24)
    assert [s.id for s in due] == ["b", "c", "d"]


def test_check_interval_reads_the_config_with_a_default() -> None:
    assert ui.check_interval_hours({"check_interval_hours": 6}) == 6
    assert ui.check_interval_hours(None) == 24
    assert ui.check_interval_hours({"check_interval_hours": "x"}) == 24
    assert ui.check_interval_hours({"check_interval_hours": 0}) == 24
    assert ui.check_interval_hours({"check_interval_hours": True}) == 24


def test_apply_check_success_records_the_available_version() -> None:
    deck = build_deck()
    version = deck["deck"]["version"]
    out = ui.apply_check(
        _sub(installed_version="old", last_error="http_error"),
        FetchedDeck(deck, "etag-1"),
        "T",
    )
    assert (out.available_version, out.etag, out.last_error) == (
        version,
        "etag-1",
        None,
    )
    assert out.last_checked_at == "T"
    same = ui.apply_check(_sub(installed_version=version), FetchedDeck(deck, None), "T")
    assert same.available_version is None


def test_apply_check_unchanged_keeps_the_known_version() -> None:
    out = ui.apply_check(
        _sub(installed_version="v1", available_version="v2", last_error="not_found"),
        None,
        "T",
    )
    assert (out.available_version, out.last_error, out.last_checked_at) == (
        "v2",
        None,
        "T",
    )


def test_apply_check_error_is_recorded_without_touching_the_rest() -> None:
    before = _sub(installed_version="v1", available_version="v2", last_checked_at="X")
    out = ui.apply_check(before, SourceError("http_error"), "T")
    assert out.last_error == "http_error"
    assert out.last_checked_at == "X"
    assert out.available_version == "v2"


def test_pending_updates_ignores_not_installed_and_current() -> None:
    subs = [
        _sub(id="a", installed_version="v1", available_version="v2"),
        _sub(id="b", installed_version="v1", available_version="v1"),
        _sub(id="c", available_version="v1"),
        _sub(id="d", installed_version="v1"),
    ]
    assert [s.id for s in ui.pending_updates(subs)] == ["a"]


def test_guid_search_escapes_special_characters() -> None:
    assert ui.guid_search(["abc"]) == '"guid:abc"'
    assert ui.guid_search(["a", "b"]) == '"guid:a" or "guid:b"'
    assert ui.guid_search(['a"b*c_d\\e']) == '"guid:a\\"b\\*c\\_d\\\\e"'


def test_clears_undo_only_when_a_declared_anki_id_notetype_is_created() -> None:
    deck = build_deck()
    assert not ui.clears_undo(_plan(deck, _sub()))
    declared = build_deck()
    declared["notetypes"][0]["anki_id"] = 1234567890123
    assert ui.clears_undo(_plan(declared, _sub()))


def test_section_lines_include_summary_and_undo_warning() -> None:
    declared = build_deck()
    declared["notetypes"][0]["anki_id"] = 1234567890123
    review = ui.Review(_sub(), _plan(declared, _sub()), None)
    lines = ui.section_lines(review, "en")
    assert lines[0].startswith("Hello World (en) — ")
    assert "Undo history will be cleared" in lines[-1]
    assert "historique d'annulation" in ui.section_lines(review, "fr")[-1]
    plain = ui.Review(_sub(), _plan(build_deck(), _sub()), None)
    assert not any("Undo" in line for line in ui.section_lines(plain, "en"))


def test_section_lines_for_blocked_plan_and_error() -> None:
    blocked = replace(_plan(build_deck(), _sub()), blocked="Because.")
    lines = ui.section_lines(ui.Review(_sub(), blocked, None), "en")
    assert lines[-1] == "Because."
    err = ui.section_lines(ui.Review(_sub(), None, "http_error"), "en")
    assert any("Offline" in line for line in err)


def test_new_subscription_from_a_fetched_deck() -> None:
    deck = build_deck()
    source = parse_source("https://github.com/o/r")
    sub = ui.new_subscription(
        source, "https://base.test/en/", FetchedDeck(deck, "e"), "id1"
    )
    info = deck["deck"]
    assert (sub.id, sub.source_url, sub.base_url) == (
        "id1",
        "https://github.com/o/r",
        "https://base.test/en/",
    )
    assert (sub.deck_id, sub.edition, sub.name) == (
        info["id"],
        info["edition"],
        info["name"],
    )
    assert sub.installed_version is None
    assert sub.available_version == info["version"]
