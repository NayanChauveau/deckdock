import ast
import importlib
import sys
from pathlib import Path

import pytest

import deckdock_addon

ADDON_SRC = Path(deckdock_addon.__file__).resolve().parent
LIB_SRC = Path(__file__).resolve().parents[2] / "cli" / "src" / "deckdock"


def _lib_files(root: Path) -> set[Path]:
    return {
        p.relative_to(root)
        for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and (p.suffix == ".py" or p.name == "py.typed")
    }


def test_vendored_copy_matches_library() -> None:
    vendored = deckdock_addon.VENDOR_DIR / "deckdock"
    expected = _lib_files(LIB_SRC)
    assert expected
    assert _lib_files(vendored) == expected
    for rel in expected:
        assert (vendored / rel).read_bytes() == (LIB_SRC / rel).read_bytes(), rel


def test_import_does_not_require_aqt(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "aqt" not in sys.modules
    monkeypatch.delitem(sys.modules, "deckdock_addon")
    monkeypatch.delitem(sys.modules, "deckdock_addon.ui", raising=False)
    _ = importlib.import_module("deckdock_addon")
    assert "deckdock_addon.ui" not in sys.modules
    assert str(deckdock_addon.VENDOR_DIR) in sys.path


@pytest.mark.parametrize("name", ["engine.py", "sources.py"])
def test_engine_modules_do_not_import_anki(name: str) -> None:
    path = ADDON_SRC / name
    if not path.exists():
        pytest.skip(f"{name} does not exist yet")
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots = [node.module.split(".")[0]]
        else:
            continue
        assert not {"anki", "aqt"} & set(roots), f"{name} imports {roots}"
