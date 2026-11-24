import ast
import json
import pathlib
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
    # matching, unknown notetype, total size) are only enforced by the checker.
    cross_object = {
        "duplicate-notetype-id", "duplicate-guid", "unknown-notetype", "note-missing-field",
        "note-unknown-field", "duplicate-media-filename", "media-total-too-large",
    }
    for p in INVALID:
        if p.stem not in cross_object:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(load(p), SCHEMA)


def test_format_module_is_stdlib_only():
    files = [*sorted((SRC / "format").glob("*.py")), SRC / "guid.py"]
    assert len(files) >= 3
    banned = ("pydantic", "yaml", "markdown_it")
    for file in files:
        for node in ast.walk(ast.parse(file.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(banned), f"{file.name} imports {name}"
