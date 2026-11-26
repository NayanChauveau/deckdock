import ast
import json
import pathlib
import sys
from typing import Any, cast

import jsonschema
import pytest

from deckdock.format import check_deck

SPEC = pathlib.Path(__file__).parents[2] / "spec"
SRC = pathlib.Path(__file__).parents[1] / "src" / "deckdock"


def load(path: pathlib.Path) -> dict[str, Any]:  # pyright: ignore[reportExplicitAny]
    return cast(dict[str, Any], json.loads(path.read_text()))  # pyright: ignore[reportExplicitAny]


SCHEMA = load(SPEC / "deckdock-1.schema.json")
VALID = sorted((SPEC / "examples/valid").glob("*.json"))
INVALID = sorted((SPEC / "examples/invalid").glob("*.json"))


@pytest.mark.parametrize("p", VALID, ids=[p.name for p in VALID])
def test_valid_examples_pass_checker_and_schema(p: pathlib.Path):
    data = load(p)
    assert check_deck(data) == []
    jsonschema.validate(data, SCHEMA)


@pytest.mark.parametrize("p", INVALID, ids=[p.name for p in INVALID])
def test_invalid_examples_fail_checker(p: pathlib.Path):
    assert check_deck(load(p)) != []


def test_schema_is_a_valid_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_schema_rejects_structural_invalid_examples():
    # Structural rules live in the schema too; cross-object rules (duplicates, field
    # matching, unknown notetype, total size) and the single-emoji icon rule are only
    # enforced by the checker.
    cross_object = {
        "duplicate-notetype-id",
        "duplicate-guid",
        "unknown-notetype",
        "note-missing-field",
        "note-unknown-field",
        "duplicate-media-filename",
        "media-total-too-large",
        "deck-icon-two-emoji",
    }
    for p in INVALID:
        if p.stem not in cross_object:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(load(p), SCHEMA)


def _imported_modules(file: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(file.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_format_module_is_stdlib_only():
    files = [*sorted((SRC / "format").glob("*.py")), SRC / "guid.py", SRC / "issues.py"]
    covered = {f.relative_to(SRC).as_posix() for f in files}
    assert {"format/check.py", "format/types.py", "guid.py", "issues.py"} <= covered
    allowed = set(sys.stdlib_module_names) | {"deckdock"}
    for file in files:
        extra = _imported_modules(file) - allowed
        assert not extra, f"{file.name} imports {sorted(extra)}"


def test_package_has_no_third_party_imports():
    files = sorted(SRC.rglob("*.py"))
    assert len(files) >= 7
    allowed = set(sys.stdlib_module_names) | {"deckdock"}
    for file in files:
        extra = _imported_modules(file) - allowed
        assert not extra, f"{file.relative_to(SRC)} imports {sorted(extra)}"
