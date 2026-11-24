"""The compiled deckdock/1 format: constants and the checker (standard library only)."""

from deckdock.format.check import (
    FORMAT,
    MAX_MEDIA_BYTES,
    MAX_NOTES,
    MAX_TOTAL_MEDIA_BYTES,
    SLUG_RE,
    check_deck,
    check_dist,
)

__all__ = [
    "FORMAT",
    "MAX_MEDIA_BYTES",
    "MAX_NOTES",
    "MAX_TOTAL_MEDIA_BYTES",
    "SLUG_RE",
    "check_deck",
    "check_dist",
]
