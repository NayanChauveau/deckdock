"""Build dist/deckdock-<version>.ankiaddon from src/deckdock_addon."""

import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "deckdock_addon"
EXCLUDED_DIRS = {"__pycache__", "tests", ".venv"}


def _included(path: Path) -> bool:
    rel = path.relative_to(PACKAGE)
    if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
        return False
    name = rel.name
    return not (
        name.endswith(".pyc") or name == "meta.json" or name.startswith("_deckdock_")
    )


def build(dist: Path = ROOT / "dist") -> Path:
    """Write the .ankiaddon zip (files at the archive root) and return its path."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    dist.mkdir(parents=True, exist_ok=True)
    out = dist / f"deckdock-{version}.ankiaddon"
    out.unlink(missing_ok=True)
    files = sorted(p for p in PACKAGE.rglob("*") if p.is_file() and _included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(PACKAGE).as_posix())
    return out


if __name__ == "__main__":
    print(build())
