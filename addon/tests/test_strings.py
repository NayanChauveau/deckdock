"""Interface copy: complete FR/EN catalogs and language selection."""

from __future__ import annotations

from typing import get_args

import anki.lang
import pytest

from deckdock_addon import engine, strings
from deckdock_addon.sources import SourceError
from deckdock_addon.store import Subscription

# Every code `sources.py` raises (a test below checks this list against the source).
SOURCE_CODES = (
    "invalid_url",
    "https_required",
    "redirect_rejected",
    "http_error",
    "too_large",
    "not_found",
    "invalid_json",
    "invalid_deck",
    "sha_mismatch",
    "cancelled",
)
ADAPTER_CODES = ("deck_name_conflict", "collection_changed", "partial_apply")


def _set_language(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    monkeypatch.setattr(anki.lang, "current_i18n", object())
    monkeypatch.setattr(anki.lang, "current_lang", code)


def _sub(**overrides: object) -> Subscription:
    data: dict[str, object] = {
        "id": "s1",
        "source_url": "https://github.com/o/r",
        "base_url": "https://example.test/en/",
        "deck_id": "d",
        "edition": "en",
        "name": "Deck",
    }
    data.update(overrides)
    return Subscription(**data)  # pyright: ignore[reportArgumentType]


def test_catalogs_have_the_same_keys() -> None:
    assert strings.FR.keys() == strings.EN.keys()
    assert all(strings.FR[k] and strings.EN[k] for k in strings.FR)


def test_french_anki_selects_french(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_language(monkeypatch, "fr_FR")
    assert strings.language() == "fr"
    assert strings.ADD == "Ajouter"


def test_other_language_selects_english(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_language(monkeypatch, "de")
    assert strings.language() == "en"
    assert strings.ADD == "Add"


@pytest.mark.parametrize("code", [*SOURCE_CODES, *ADAPTER_CODES])
def test_every_error_code_has_both_texts(code: str) -> None:
    assert strings.FR[f"ERR_{code}"]
    assert strings.EN[f"ERR_{code}"]


def test_unknown_error_code_falls_back_to_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_language(monkeypatch, "de")
    assert strings.error_text("nope") == strings.EN["ERROR"]
    assert strings.error_text(None) == strings.EN["ERROR"]
    assert strings.error_text("not_found") == strings.EN["ERR_not_found"]


def test_source_codes_match_the_codes_raised_by_sources() -> None:
    import inspect
    import re

    from deckdock_addon import sources

    raised = set(re.findall(r'SourceError\(\s*"([a-z_]+)"', inspect.getsource(sources)))
    assert raised <= set(SOURCE_CODES)
    assert issubclass(SourceError, Exception)


@pytest.mark.parametrize("reason", get_args(engine.SkipReason))
def test_every_skip_reason_has_both_texts(reason: str) -> None:
    assert strings.FR[f"SKIP_{reason}"]
    assert strings.EN[f"SKIP_{reason}"]


def test_status_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_language(monkeypatch, "de")
    assert strings.status_text(_sub()) == "Not installed"
    installed = _sub(installed_version="v1")
    assert strings.status_text(installed) == "Up to date"
    newer = _sub(installed_version="v1", available_version="v2")
    assert strings.status_text(newer) == "Update available"
    failed = _sub(installed_version="v1", last_error="http_error")
    assert strings.status_text(failed) == strings.EN["ERR_http_error"]
    _set_language(monkeypatch, "fr_FR")
    assert strings.status_text(newer) == "Mise à jour disponible"


def test_version_text() -> None:
    assert strings.version_text(_sub()) == "—"
    assert strings.version_text(_sub(installed_version="v1")) == "v1"
    both = _sub(installed_version="v1", available_version="v2")
    assert strings.version_text(both) == "v1 → v2"
    assert strings.version_text(_sub(available_version="v2")) == "v2"


def test_undo_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_language(monkeypatch, "de")
    assert strings.undo_label("Deck") == "DeckDock: update Deck"
    _set_language(monkeypatch, "fr")
    assert strings.undo_label("Deck") == "DeckDock : mise à jour de Deck"
