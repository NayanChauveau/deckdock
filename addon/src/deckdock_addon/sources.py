"""Source URLs and HTTPS access to index.json, deck.json and media (no Anki imports).

Every request is HTTPS only, redirects included. Responses are read with a hard
byte cap, so a hostile server cannot make the add-on buffer an unbounded body.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast, override
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from deckdock.format import MAX_MEDIA_BYTES, CompiledDeck, MediaEntry, check_deck

USER_AGENT = "DeckDock"
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5
MAX_DECK_BYTES = 67_108_864
MAX_INDEX_BYTES = 1_048_576
INDEX_FORMAT = "deckdock-index/1"

_CHUNK_BYTES = 64 * 1024
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class SourceError(Exception):
    """A source could not be read; `code` is a stable machine-readable reason."""

    code: str

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], int], Response]


# --- URLs ------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    kind: Literal["github", "base"]
    url: str
    index_url: str | None
    owner: str | None
    repo: str | None


@dataclass(frozen=True)
class IndexEdition:
    edition: str
    name: str
    language: list[str]
    version: str


def _raw_base(owner: str, repo: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/dist/"


def parse_source(text: str) -> Source:
    url = text.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        raise SourceError("invalid_url", url)
    if parts.hostname.lower() in _GITHUB_HOSTS:
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) != 2 or parts.path.endswith("//"):
            raise SourceError("invalid_url", url)
        owner, repo = segments[0], segments[1].removesuffix(".git")
        if not (_GITHUB_NAME.match(owner) and _GITHUB_NAME.match(repo)) or repo in {
            "",
            ".",
            "..",
        }:
            raise SourceError("invalid_url", url)
        return Source(
            "github",
            f"https://github.com/{owner}/{repo}",
            _raw_base(owner, repo) + "index.json",
            owner,
            repo,
        )
    if not parts.path.endswith("/"):
        raise SourceError("invalid_url", url)
    return Source("base", url, None, None, None)


def edition_base_url(source: Source, edition: str) -> str:
    if source.kind == "github" and source.owner and source.repo:
        return f"{_raw_base(source.owner, source.repo)}{quote(edition, safe='')}/"
    return source.url


# --- Transport -------------------------------------------------------------------


class _NoRedirect(HTTPRedirectHandler):
    """Surface redirects as HTTPError so the caller can vet each hop."""

    @override
    def redirect_request(
        self,
        req,  # pyright: ignore[reportMissingParameterType]
        fp,  # pyright: ignore[reportMissingParameterType]
        code,  # pyright: ignore[reportMissingParameterType]
        msg,  # pyright: ignore[reportMissingParameterType]
        headers,  # pyright: ignore[reportMissingParameterType]
        newurl,  # pyright: ignore[reportMissingParameterType]
    ):
        return None


class RawResponse(Protocol):
    """The slice of an HTTP response (or HTTPError) that the transport uses."""

    @property
    def status(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    def read(self, size: int = -1, /) -> bytes: ...
    def close(self) -> None: ...


Opener = Callable[[Request], RawResponse]


def _default_opener(request: Request) -> RawResponse:
    return cast(
        RawResponse, build_opener(_NoRedirect).open(request, timeout=TIMEOUT_SECONDS)
    )


def _lower(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _read_capped(response: RawResponse, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(_CHUNK_BYTES)
        if not block:
            return b"".join(chunks)
        total += len(block)
        if total > max_bytes:
            raise SourceError("too_large")
        chunks.append(block)


def _require_https(url: str, code: str) -> None:
    if urlsplit(url).scheme != "https":
        raise SourceError(code, url)


def urllib_transport(
    url: str,
    headers: dict[str, str],
    max_bytes: int,
    *,
    opener: Opener = _default_opener,
) -> Response:
    """GET `url` over HTTPS, following at most 5 HTTPS redirects, reading at most `max_bytes`."""
    current = url
    _require_https(current, "https_required")
    for _hop in range(MAX_REDIRECTS + 1):
        request = Request(
            current, headers={"User-Agent": USER_AGENT, **headers}, method="GET"
        )
        try:
            response = opener(request)
        except HTTPError as exc:
            response = cast(RawResponse, cast(object, exc))
        except (URLError, OSError) as exc:
            raise SourceError("http_error", str(exc)) from exc
        try:
            status = response.status
            response_headers = _lower(response.headers)
            if status in _REDIRECT_STATUSES:
                location = response_headers.get("location")
                if not location:
                    raise SourceError("redirect_rejected", current)
                current = urljoin(current, location)
                _require_https(current, "redirect_rejected")
                continue
            if status == 404 or status == 304:
                return Response(status, response_headers, b"")
            if not 200 <= status < 300:
                raise SourceError("http_error", f"HTTP {status}")
            length = response_headers.get("content-length", "")
            if length.isdigit() and int(length) > max_bytes:
                raise SourceError("too_large")
            try:
                body = _read_capped(response, max_bytes)
            except OSError as exc:
                raise SourceError("http_error", str(exc)) from exc
            return Response(status, response_headers, body)
        finally:
            response.close()
    raise SourceError("redirect_rejected", "too many redirects")


# --- index.json, deck.json, media ------------------------------------------------


def _get(
    transport: Transport, url: str, headers: dict[str, str], max_bytes: int
) -> Response:
    response = transport(url, headers, max_bytes)
    if response.status == 404:
        raise SourceError("not_found", url)
    if response.status != 304 and not 200 <= response.status < 300:
        raise SourceError("http_error", f"HTTP {response.status}")
    return response


def _json_object(body: bytes, what: str) -> dict[str, object]:
    try:
        data = cast(object, json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SourceError("invalid_json", f"{what}: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceError("invalid_json", f"{what}: expected a JSON object")
    return cast("dict[str, object]", data)


def fetch_index(
    source: Source, *, transport: Transport = urllib_transport
) -> list[IndexEdition]:
    if source.index_url is None:
        raise SourceError("invalid_url", "this source has no index")
    response = _get(transport, source.index_url, {}, MAX_INDEX_BYTES)
    data = _json_object(response.body, "index.json")
    if data.get("format") != INDEX_FORMAT:
        raise SourceError("invalid_json", f"index.json: expected format {INDEX_FORMAT}")
    raw = data.get("editions")
    if not isinstance(raw, list):
        raise SourceError("invalid_json", "index.json: editions must be a list")
    editions: list[IndexEdition] = []
    for item in cast("list[object]", raw):
        if not isinstance(item, dict):
            raise SourceError("invalid_json", "index.json: invalid edition entry")
        entry = cast("dict[str, object]", item)
        edition, name, version = (
            entry.get("edition"),
            entry.get("name"),
            entry.get("version"),
        )
        language = entry.get("language")
        if (
            not isinstance(edition, str)
            or not isinstance(name, str)
            or not isinstance(version, str)
            or not isinstance(language, list)
            or not all(isinstance(x, str) for x in cast("list[object]", language))
        ):
            raise SourceError("invalid_json", "index.json: invalid edition entry")
        editions.append(
            IndexEdition(edition, name, cast("list[str]", language), version)
        )
    return editions


@dataclass(frozen=True)
class FetchedDeck:
    deck: CompiledDeck
    etag: str | None


def fetch_deck(
    base_url: str, *, etag: str | None, transport: Transport = urllib_transport
) -> FetchedDeck | None:
    """Read `<base_url>deck.json`; `None` means unchanged since `etag` (HTTP 304)."""
    headers = {"If-None-Match": etag} if etag else {}
    response = _get(transport, base_url + "deck.json", headers, MAX_DECK_BYTES)
    if response.status == 304:
        return None
    data = _json_object(response.body, "deck.json")
    issues = check_deck(data, strict=False)
    if issues:
        raise SourceError("invalid_deck", str(issues[0]))
    return FetchedDeck(
        cast(CompiledDeck, cast(object, data)), response.headers.get("etag")
    )


def fetch_media(
    base_url: str,
    entry: MediaEntry,
    *,
    transport: Transport = urllib_transport,
    cancelled: Callable[[], bool] = lambda: False,
) -> bytes:
    """Read one media file and check its size and sha256 against the deck entry."""
    if cancelled():
        raise SourceError("cancelled")
    url = f"{base_url}media/{quote(entry['filename'], safe='')}"
    response = _get(transport, url, {}, min(entry["size"], MAX_MEDIA_BYTES))
    body = response.body
    if (
        len(body) != entry["size"]
        or hashlib.sha256(body).hexdigest() != entry["sha256"]
    ):
        raise SourceError("sha_mismatch", entry["filename"])
    return body
