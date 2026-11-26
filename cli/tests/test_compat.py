import copy
import json
import pathlib
from collections.abc import Callable
from typing import cast

import pytest

from deckdock.compat import notetype_changes
from deckdock.format import CompiledDeck, Notetype

SPEC = pathlib.Path(__file__).parents[2] / "spec"


def base() -> CompiledDeck:
    deck = cast(
        CompiledDeck,
        json.loads((SPEC / "examples/valid/minimal.json").read_text()),
    )
    nt = deck["notetypes"][0]
    nt["fields"] = ["Front", "Back"]
    nt["templates"] = [
        {"name": "Card 1", "front": "{{Front}}", "back": "{{Back}}"},
        {"name": "Card 2", "front": "{{Back}}", "back": "{{Front}}"},
    ]
    return deck


def changed(mutate: Callable[[Notetype], None]) -> CompiledDeck:
    deck = copy.deepcopy(base())
    mutate(deck["notetypes"][0])
    return deck


def test_compat_appended_field():
    new = changed(lambda nt: nt["fields"].append("Extra"))
    result = notetype_changes(base(), new)
    assert len(result) == 1
    assert result[0].kind == "appended_fields"
    assert result[0].notetype == base()["notetypes"][0]["id"]
    assert "Extra" in result[0].detail


def _remove_field(nt: Notetype) -> None:
    nt["fields"] = ["Front"]


def _rename_field(nt: Notetype) -> None:
    nt["fields"] = ["Front", "Verso"]


def _reorder_fields(nt: Notetype) -> None:
    nt["fields"] = ["Back", "Front"]


def _add_template(nt: Notetype) -> None:
    nt["templates"].append({"name": "Card 3", "front": "x", "back": "y"})


def _remove_template(nt: Notetype) -> None:
    nt["templates"] = nt["templates"][:1]


def _change_kind(nt: Notetype) -> None:
    nt["kind"] = "cloze"


@pytest.mark.parametrize(
    "mutate",
    [
        _remove_field,
        _rename_field,
        _reorder_fields,
        _add_template,
        _remove_template,
        _change_kind,
    ],
)
def test_compat_breaking(mutate: Callable[[Notetype], None]):
    result = notetype_changes(base(), changed(mutate))
    assert [c.kind for c in result] == ["breaking"]
    assert result[0].detail


def test_compat_unchanged():
    def edit(nt: Notetype) -> None:
        nt["templates"][0]["front"] = "<b>{{Front}}</b>"
        nt["css"] = ".card { color: red; }"

    assert notetype_changes(base(), changed(edit)) == []


def test_compat_new_or_removed_notetype_is_not_a_change():
    new = copy.deepcopy(base())
    other = copy.deepcopy(new["notetypes"][0])
    other["id"] = "another"
    new["notetypes"].append(other)
    assert notetype_changes(base(), new) == []
    assert notetype_changes(new, base()) == []
