"""Shared fixtures: deckdock/1 example decks, a fake HTTPS server, a temporary collection."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection
from deckdock.format import CompiledDeck, MediaEntry, Note, Notetype

from deckdock_addon.sources import Response, SourceError
from deckdock_addon.store import Subscription

BASE_URL = "https://decks.example.test/hello-world/en/"


def png_bytes(red: int = 255, green: int = 0, blue: int = 0) -> bytes:
    """A valid 1x1 RGB PNG of the given color."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(bytes([0, red, green, blue]))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def media_entry(filename: str, data: bytes) -> MediaEntry:
    return {
        "filename": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def basic_notetype() -> Notetype:
    return {
        "id": "basic",
        "name": "Basic",
        "kind": "standard",
        "fields": ["Front", "Back"],
        "templates": [
            {
                "name": "Card 1",
                "front": "{{Front}}",
                "back": '{{FrontSide}}<hr id=answer>{{Back}}<img src="h.png">',
            }
        ],
        "css": ".card { font-family: arial; }",
    }


def reversed_notetype() -> Notetype:
    return {
        "id": "reversed",
        "name": "Basic (and reversed card)",
        "kind": "standard",
        "fields": ["Front", "Back"],
        "templates": [
            {
                "name": "Card 1",
                "front": "{{Front}}",
                "back": "{{FrontSide}}<hr id=answer>{{Back}}",
            },
            {
                "name": "Card 2",
                "front": "{{Back}}",
                "back": "{{FrontSide}}<hr id=answer>{{Front}}",
            },
        ],
        "css": ".card { color: black; }",
    }


def cloze_notetype() -> Notetype:
    return {
        "id": "cloze",
        "name": "Cloze",
        "kind": "cloze",
        "fields": ["Text", "Extra"],
        "templates": [
            {
                "name": "Cloze",
                "front": "{{cloze:Text}}",
                "back": "{{cloze:Text}}<br>{{Extra}}",
            }
        ],
        "css": ".cloze { font-weight: bold; }",
    }


def basic_note(guid: str, front: str, back: str, deck: str = "") -> Note:
    return {
        "guid": guid,
        "notetype": "basic",
        "deck": deck,
        "fields": {"Front": front, "Back": back},
        "tags": ["hello"],
    }


def build_deck(
    version: str = "1", image: bytes | None = None, notes: list[Note] | None = None
) -> CompiledDeck:
    """A Hello-World-like deck: basic (with an image), reversed and cloze notes."""
    picture = png_bytes() if image is None else image
    default_notes: list[Note] = [
        basic_note("hw-basic-1", "Hello", 'World <img src="h.png">'),
        {
            "guid": "hw-reversed-1",
            "notetype": "reversed",
            "deck": "Vocabulary",
            "fields": {"Front": "cat", "Back": "chat"},
            "tags": ["vocab"],
        },
        {
            "guid": "hw-cloze-1",
            "notetype": "cloze",
            "deck": "Vocabulary::Geography",
            "fields": {"Text": "{{c1::Paris}} is in France", "Extra": ""},
            "tags": [],
        },
    ]
    return {
        "format": "deckdock/1",
        "deck": {
            "id": "hello-world",
            "edition": "en",
            "name": "Hello World",
            "language": ["en"],
            "version": version,
        },
        "notetypes": [basic_notetype(), reversed_notetype(), cloze_notetype()],
        "notes": default_notes if notes is None else notes,
        "media": [media_entry("h.png", picture)],
    }


class FakeServer:
    """In-memory HTTPS server usable as a `Transport`.

    `decks` is a queue of deck.json bodies: each request pops the first one,
    except the last, which stays served.
    """

    def __init__(self) -> None:
        self.decks: list[bytes] = []
        self.media: dict[str, bytes] = {}
        self.failing: set[str] = set()
        self.requests: list[str] = []

    def publish(self, deck: CompiledDeck, image: bytes | None = None) -> None:
        self.decks = [json.dumps(deck).encode("utf-8")]
        if image is not None:
            self.media["h.png"] = image

    def queue(self, *decks: CompiledDeck) -> None:
        self.decks = [json.dumps(d).encode("utf-8") for d in decks]

    def __call__(self, url: str, headers: dict[str, str], max_bytes: int) -> Response:
        del headers, max_bytes
        self.requests.append(url)
        if url in self.failing:
            raise SourceError("http_error", "connection reset")
        if url == BASE_URL + "deck.json":
            body = self.decks[0] if len(self.decks) == 1 else self.decks.pop(0)
            return Response(200, {"etag": f'"{len(self.requests)}"'}, body)
        if url.startswith(BASE_URL + "media/"):
            name = url.removeprefix(BASE_URL + "media/")
            if name in self.media:
                return Response(200, {}, self.media[name])
        return Response(404, {}, b"")


@pytest.fixture
def col(tmp_path: Path) -> Iterator[Collection]:
    collection = Collection(str(tmp_path / "c.anki2"))
    try:
        yield collection
    finally:
        collection.close()


@pytest.fixture
def server() -> FakeServer:
    s = FakeServer()
    s.publish(build_deck(), png_bytes())
    return s


@pytest.fixture
def sub() -> Subscription:
    return Subscription(
        id="sub-1",
        source_url=BASE_URL,
        base_url=BASE_URL,
        deck_id="hello-world",
        edition="en",
        name="Hello World",
    )


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    return tmp_path / "profile"


def clone(deck: CompiledDeck) -> CompiledDeck:
    return copy.deepcopy(deck)
