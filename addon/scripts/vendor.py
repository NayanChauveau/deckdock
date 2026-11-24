"""Copy the deckdock library from ../cli into the add-on's vendor directory."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "cli" / "src" / "deckdock"
DEST = ROOT / "src" / "deckdock_addon" / "vendor" / "deckdock"


def vendor(src: Path, dest: Path) -> None:
    """Replace `dest` entirely with the `.py` files and `py.typed` of `src`."""
    if dest.exists():
        shutil.rmtree(dest)
    for path in sorted(src.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix != ".py" and path.name != "py.typed":
            continue
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


if __name__ == "__main__":
    vendor(SRC, DEST)
