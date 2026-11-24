import hashlib
import http.client
import io
import json
from collections.abc import Callable
from email.message import Message
from typing import cast, override
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from deckdock.format import MAX_MEDIA_BYTES, MediaEntry

from deckdock_addon import sources
from deckdock_addon.sources import (
    Response,
    Source,
    SourceError,
    edition_base_url,
    fetch_deck,
    fetch_index,
    fetch_media,
    parse_source,
    urllib_transport,
)

RAW = "https://raw.githubusercontent.com/acme/cards/dist/"


def _deck() -> dict[str, object]:
    return {
        "format": "deckdock/1",
        "deck": {
            "id": "demo",
            "edition": "fr",
            "name": "Demo",
            "language": ["fr"],
            "version": "1",
        },
        "notetypes": [
            {
                "id": "basic",
                "name": "Basic",
                "kind": "standard",
                "fields": ["Front", "Back"],
                "templates": [
                    {"name": "Card 1", "front": "{{Front}}", "back": "{{Back}}"}
                ],
                "css": "",
            }
        ],
        "notes": [
            {
                "guid": "g1",
                "notetype": "basic",
                "deck": "",
                "fields": {"Front": "a", "Back": "b"},
                "tags": [],
            }
        ],
        "media": [],
    }


class FakeTransport:
    def __init__(self, response: Response | SourceError) -> None:
        self.response: Response | SourceError = response
        self.calls: list[tuple[str, dict[str, str], int]] = []

    def __call__(self, url: str, headers: dict[str, str], max_bytes: int) -> Response:
        self.calls.append((url, headers, max_bytes))
        if isinstance(self.response, SourceError):
            raise self.response
        return self.response


def _json_response(data: object, status: int = 200, **headers: str) -> Response:
    return Response(status, dict(headers), json.dumps(data).encode())


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/acme/cards",
        "https://github.com/acme/cards/",
        "https://github.com/acme/cards.git",
        "https://www.github.com/acme/cards",
    ],
)
def test_parse_github_repo_variants(text: str) -> None:
    source = parse_source(text)
    assert source.kind == "github"
    assert source.owner == "acme"
    assert source.repo == "cards"
    assert source.index_url == RAW + "index.json"


@pytest.mark.parametrize(
    "text",
    [
        "http://example.com/decks/",
        "https://example.com/decks",
        "ftp://example.com/",
        "example.com/decks/",
        "",
        "https://github.com/acme",
        "https://github.com/acme/cards/tree/main",
    ],
)
def test_parse_base_url_requires_trailing_slash_and_https(text: str) -> None:
    with pytest.raises(SourceError) as exc:
        _ = parse_source(text)
    assert exc.value.code == "invalid_url"


def test_parse_base_url() -> None:
    source = parse_source("  https://example.com/decks/fr/  ")
    assert source == Source("base", "https://example.com/decks/fr/", None, None, None)


def test_edition_base_url() -> None:
    assert (
        edition_base_url(parse_source("https://github.com/acme/cards"), "fr")
        == RAW + "fr/"
    )
    base = parse_source("https://example.com/decks/fr/")
    assert edition_base_url(base, "fr") == "https://example.com/decks/fr/"


def test_fetch_index_parses_editions() -> None:
    data = {
        "format": "deckdock-index/1",
        "editions": [
            {"edition": "fr", "name": "Demo", "language": ["fr"], "version": "3"}
        ],
    }
    transport = FakeTransport(_json_response(data))
    editions = fetch_index(
        parse_source("https://github.com/acme/cards"), transport=transport
    )
    assert [(e.edition, e.name, e.language, e.version) for e in editions] == [
        ("fr", "Demo", ["fr"], "3")
    ]
    assert transport.calls[0][0] == RAW + "index.json"
    assert transport.calls[0][2] == 1_048_576


def test_fetch_index_rejects_unknown_format() -> None:
    transport = FakeTransport(_json_response({"format": "other/1", "editions": []}))
    with pytest.raises(SourceError) as exc:
        _ = fetch_index(
            parse_source("https://github.com/acme/cards"), transport=transport
        )
    assert exc.value.code == "invalid_json"


def test_fetch_index_rejects_garbage() -> None:
    transport = FakeTransport(Response(200, {}, b"\xff not json"))
    with pytest.raises(SourceError) as exc:
        _ = fetch_index(
            parse_source("https://github.com/acme/cards"), transport=transport
        )
    assert exc.value.code == "invalid_json"


def test_fetch_index_needs_an_index_url() -> None:
    with pytest.raises(SourceError) as exc:
        _ = fetch_index(
            parse_source("https://example.com/decks/"),
            transport=FakeTransport(_json_response({})),
        )
    assert exc.value.code == "invalid_url"


def test_fetch_deck_sends_if_none_match_and_handles_304() -> None:
    transport = FakeTransport(Response(304, {}, b""))
    assert fetch_deck(RAW + "fr/", etag='"abc"', transport=transport) is None
    url, headers, _cap = transport.calls[0]
    assert url == RAW + "fr/deck.json"
    assert headers["If-None-Match"] == '"abc"'

    ok = FakeTransport(_json_response(_deck(), etag='"new"'))
    fetched = fetch_deck(RAW + "fr/", etag=None, transport=ok)
    assert fetched is not None
    assert fetched.etag == '"new"'
    assert fetched.deck["deck"]["id"] == "demo"
    assert "If-None-Match" not in ok.calls[0][1]


def test_fetch_deck_rejects_invalid_deck() -> None:
    data = _deck()
    del data["notes"]
    with pytest.raises(SourceError) as exc:
        _ = fetch_deck(RAW, etag=None, transport=FakeTransport(_json_response(data)))
    assert exc.value.code == "invalid_deck"
    assert "notes" in str(exc.value)


def test_fetch_deck_rejects_non_object_and_bad_utf8() -> None:
    for body in (b"[1]", b"\xff\xfe"):
        with pytest.raises(SourceError) as exc:
            _ = fetch_deck(
                RAW, etag=None, transport=FakeTransport(Response(200, {}, body))
            )
        assert exc.value.code == "invalid_json"


def test_fetch_deck_accepts_unknown_keys() -> None:
    data = _deck()
    data["future"] = {"x": 1}
    fetched = fetch_deck(RAW, etag=None, transport=FakeTransport(_json_response(data)))
    assert fetched is not None
    assert fetched.etag is None


def test_fetch_deck_too_large() -> None:
    transport = FakeTransport(SourceError("too_large"))
    with pytest.raises(SourceError) as exc:
        _ = fetch_deck(RAW, etag=None, transport=transport)
    assert exc.value.code == "too_large"
    assert transport.calls[0][2] == 67_108_864


def _entry(data: bytes, filename: str = "a.png") -> MediaEntry:
    return {
        "filename": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def test_fetch_media_checks_sha_and_size() -> None:
    data = b"png-bytes"
    transport = FakeTransport(Response(200, {}, data))
    assert fetch_media(RAW, _entry(data), transport=transport) == data
    assert transport.calls[0][2] == len(data)

    for body in (b"png-byteX", b"png-byte"):
        with pytest.raises(SourceError) as exc:
            _ = fetch_media(
                RAW, _entry(data), transport=FakeTransport(Response(200, {}, body))
            )
        assert exc.value.code == "sha_mismatch"


def test_fetch_media_caps_at_max_media_bytes() -> None:
    entry: MediaEntry = {
        "filename": "a.png",
        "sha256": "0" * 64,
        "size": MAX_MEDIA_BYTES * 2,
    }
    transport = FakeTransport(Response(200, {}, b""))
    with pytest.raises(SourceError):
        _ = fetch_media(RAW, entry, transport=transport)
    assert transport.calls[0][2] == MAX_MEDIA_BYTES


def test_fetch_media_quotes_name() -> None:
    data = b"x"
    transport = FakeTransport(Response(200, {}, data))
    _ = fetch_media(RAW + "fr/", _entry(data, "a b.png"), transport=transport)
    assert transport.calls[0][0] == RAW + "fr/media/a%20b.png"


def test_fetch_media_cancelled_before_request() -> None:
    transport = FakeTransport(Response(200, {}, b"x"))
    with pytest.raises(SourceError) as exc:
        _ = fetch_media(RAW, _entry(b"x"), transport=transport, cancelled=lambda: True)
    assert exc.value.code == "cancelled"
    assert transport.calls == []


def test_404_maps_to_not_found() -> None:
    transport = FakeTransport(Response(404, {}, b""))
    with pytest.raises(SourceError) as exc:
        _ = fetch_deck(RAW, etag=None, transport=transport)
    assert exc.value.code == "not_found"
    with pytest.raises(SourceError) as exc:
        _ = fetch_media(RAW, _entry(b"x"), transport=transport)
    assert exc.value.code == "not_found"


def test_server_error_maps_to_http_error() -> None:
    with pytest.raises(SourceError) as exc:
        _ = fetch_deck(RAW, etag=None, transport=FakeTransport(Response(500, {}, b"")))
    assert exc.value.code == "http_error"


# --- urllib_transport, with a fake opener ---------------------------------------


class FakeHttpResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status: int = status
        self.headers: dict[str, str] = headers
        self._body: io.BytesIO = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        return None


def _redirect(url: str, location: str, code: int = 302) -> HTTPError:
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, code, "redirect", headers, None)


class FakeOpener:
    def __init__(self, script: dict[str, Callable[[], object]]) -> None:
        self.script: dict[str, Callable[[], object]] = script
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> FakeHttpResponse:
        self.requests.append(request)
        result = self.script[request.full_url]()
        if isinstance(result, BaseException):
            raise result
        return cast(FakeHttpResponse, result)


def test_redirect_to_http_rejected() -> None:
    opener = FakeOpener(
        {"https://a.test/x": lambda: _redirect("https://a.test/x", "http://a.test/y")}
    )
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=opener)
    assert exc.value.code == "redirect_rejected"
    assert len(opener.requests) == 1


def test_invalid_redirect_location_rejected() -> None:
    opener = FakeOpener(
        {"https://a.test/x": lambda: _redirect("https://a.test/x", "https://[bad/x")}
    )
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=opener)
    assert exc.value.code == "redirect_rejected"


def test_http_initial_url_rejected() -> None:
    opener = FakeOpener({})
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("http://a.test/x", {}, 100, opener=opener)
    assert exc.value.code == "https_required"
    assert opener.requests == []


def test_https_redirect_followed_and_headers_sent() -> None:
    opener = FakeOpener(
        {
            "https://a.test/x": lambda: _redirect("https://a.test/x", "/y"),
            "https://a.test/y": lambda: FakeHttpResponse(
                200, {"ETag": '"e"'}, b"hello"
            ),
        }
    )
    response = urllib_transport(
        "https://a.test/x", {"If-None-Match": '"q"'}, 100, opener=opener
    )
    assert (response.status, response.body, response.headers["etag"]) == (
        200,
        b"hello",
        '"e"',
    )
    assert opener.requests[0].get_header("User-agent") == "DeckDock"
    assert opener.requests[1].get_header("If-none-match") == '"q"'


def test_too_many_redirects() -> None:
    opener = FakeOpener(
        {"https://a.test/x": lambda: _redirect("https://a.test/x", "https://a.test/x")}
    )
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=opener)
    assert exc.value.code == "redirect_rejected"
    assert len(opener.requests) == 6


def test_transport_caps_content_length_and_stream() -> None:
    big_header = FakeOpener(
        {
            "https://a.test/x": lambda: FakeHttpResponse(
                200, {"Content-Length": "101"}, b""
            )
        }
    )
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=big_header)
    assert exc.value.code == "too_large"

    streamed = FakeOpener(
        {"https://a.test/x": lambda: FakeHttpResponse(200, {}, b"x" * 101)}
    )
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=streamed)
    assert exc.value.code == "too_large"


def test_transport_status_mapping() -> None:
    def err(code: int) -> HTTPError:
        return HTTPError("https://a.test/x", code, "e", Message(), None)

    not_found = FakeOpener({"https://a.test/x": lambda: err(404)})
    assert urllib_transport("https://a.test/x", {}, 100, opener=not_found).status == 404
    not_modified = FakeOpener({"https://a.test/x": lambda: err(304)})
    assert (
        urllib_transport("https://a.test/x", {}, 100, opener=not_modified).status == 304
    )
    boom = FakeOpener({"https://a.test/x": lambda: err(503)})
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=boom)
    assert exc.value.code == "http_error"
    net = FakeOpener({"https://a.test/x": lambda: OSError("down")})
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=net)
    assert exc.value.code == "http_error"


def test_module_exposes_transport_alias() -> None:
    assert sources.Transport is not None


class BrokenBody(FakeHttpResponse):
    @override
    def read(self, size: int = -1) -> bytes:
        raise http.client.IncompleteRead(b"par", 10)


@pytest.mark.parametrize(
    "failure",
    [
        lambda: BrokenBody(200, {}),
        lambda: http.client.InvalidURL("control characters"),
        lambda: http.client.BadStatusLine("garbage"),
        lambda: UnicodeEncodeError("latin-1", "é\u4e2d", 1, 2, "bad"),
    ],
)
def test_transport_maps_protocol_errors_to_http_error(
    failure: Callable[[], object],
) -> None:
    opener = FakeOpener({"https://a.test/x": failure})
    with pytest.raises(SourceError) as exc:
        _ = urllib_transport("https://a.test/x", {}, 100, opener=opener)
    assert exc.value.code == "http_error"


def test_deeply_nested_json_is_invalid_json() -> None:
    body = b"[" * 200_000 + b"]" * 200_000
    with pytest.raises(SourceError) as exc:
        _ = fetch_deck(RAW, etag=None, transport=FakeTransport(Response(200, {}, body)))
    assert exc.value.code == "invalid_json"
