import importlib.util
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parent.parent


def _load_package_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "deckdock_package_script", ROOT / "scripts" / "package.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_contains_addon_files_only(tmp_path: Path) -> None:
    script = _load_package_script()
    project = cast(
        dict[str, str], tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    )
    version = project["version"]

    # Stray files that must never end up in the package.
    pkg = ROOT / "src" / "deckdock_addon"
    stray = [
        pkg / "meta.json",
        pkg / "_deckdock_tmp.json",
        pkg / "stray.pyc",
        pkg / "tests" / "test_x.py",
        pkg / ".venv" / "pyvenv.cfg",
    ]
    try:
        for path in stray:
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text("x")
        build = cast(Callable[[Path], Path], getattr(script, "build"))  # noqa: B009
        out = build(tmp_path)
    finally:
        for path in stray:
            path.unlink(missing_ok=True)
        for directory in (pkg / "tests", pkg / ".venv"):
            if directory.is_dir():
                directory.rmdir()

    assert out.name == f"deckdock-{version}.ankiaddon"
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())

    for required in (
        "__init__.py",
        "manifest.json",
        "config.json",
        "engine.py",
        "adapter.py",
        "sources.py",
        "store.py",
        "strings.py",
        "ui.py",
        "vendor/deckdock/__init__.py",
    ):
        assert required in names, required
    assert any(n.startswith("vendor/deckdock/") for n in names)
    for name in names:
        parts = name.split("/")
        assert "__pycache__" not in parts
        assert "tests" not in parts
        assert ".venv" not in parts
        assert not name.endswith(".pyc")
        assert parts[-1] != "meta.json"
        assert not parts[-1].startswith("_deckdock_")
        assert not name.startswith("deckdock_addon/")
