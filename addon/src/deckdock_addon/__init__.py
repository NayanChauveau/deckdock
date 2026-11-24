"""DeckDock Anki add-on."""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"

# Make `import deckdock` resolve to the embedded copy.
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

if importlib.util.find_spec("aqt") is not None:
    _register = cast(
        Callable[[], None],
        importlib.import_module(".ui", __package__).register,
    )
    _register()
