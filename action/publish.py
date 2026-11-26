#!/usr/bin/env python3
"""Publish compiled DeckDock editions to a hub: the Action's `publish` command.

The implementation is the library's `deckdock.publish` (also behind `deckdock publish`), imported
from this checkout of the repository: nothing is installed, and only the standard library runs.

Configuration comes from the environment (set by action.yml):
  DECKDOCK_HUB_URL  hub base URL (https, or http on localhost)
  DECKDOCK_TOKEN    per-deck bearer token (never printed)
  DECKDOCK_PATH     compiled dist folder (default: dist)
  DECKDOCK_MAX_BYTES  largest archive sent, in bytes (default: 104857600, the
                    hub's default upload limit); a larger one fails before sending
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli" / "src"))

from deckdock.publish import (  # noqa: E402
    DEFAULT_MAX_BYTES,
    POST_TIMEOUT,
    main_from_env,
)

__all__ = ["DEFAULT_MAX_BYTES", "POST_TIMEOUT", "main_from_env"]

if __name__ == "__main__":
    sys.exit(main_from_env(os.environ))
