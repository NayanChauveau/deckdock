import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast, override

import pytest

from deckdock.cli import main

TOKEN = "s3cr3t-token-value"


class Hub:
    """A fake hub on 127.0.0.1; `statuses` gives the HTTP status of each POST in turn."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self.statuses: list[int] = statuses or []
        self.requests: list[dict[str, str]] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                _ = self.rfile.read(length)
                hub.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization") or ""}
                )
                status = hub.statuses.pop(0) if hub.statuses else 200
                body: dict[str, object] = (
                    {"status": "published", "version": "v1", "notes": 3, "warnings": []}
                    if status < 400
                    else {"errors": [{"where": "notes[0]", "message": "bad"}]}
                )
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                _ = self.wfile.write(data)

            @override
            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server: HTTPServer = HTTPServer(("127.0.0.1", 0), Handler)
        self.url: str = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def hub() -> Iterator[Hub]:
    h = Hub()
    yield h
    h.close()


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    for edition in ("en", "fr"):
        (tmp_path / edition / "media").mkdir(parents=True)
        _ = (tmp_path / edition / "deck.json").write_text(f'{{"edition": "{edition}"}}')
    return tmp_path


@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKDOCK_TOKEN", TOKEN)
    monkeypatch.delenv("DECKDOCK_HUB_URL", raising=False)


def test_cli_publishes_each_edition_and_prints_plain_text(
    hub: Hub, dist: Path, capsys: pytest.CaptureFixture[str]
):
    assert main(["publish", str(dist), "--hub", hub.url]) == 0
    assert [r["path"] for r in hub.requests] == ["/api/publish/en", "/api/publish/fr"]
    assert all(r["auth"] == f"Bearer {TOKEN}" for r in hub.requests)
    out = capsys.readouterr()
    assert "::" not in out.out + out.err
    assert "en: published (version v1, 3 notes)" in out.out


def test_cli_hub_url_from_environment(
    hub: Hub, dist: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DECKDOCK_HUB_URL", hub.url)
    assert main(["publish", str(dist)]) == 0
    assert len(hub.requests) == 2


def test_cli_json_report(hub: Hub, dist: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["publish", str(dist), "--hub", hub.url, "--json"]) == 0
    report = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert report["ok"] is True
    editions = cast(list[dict[str, object]], report["editions"])
    assert [e["edition"] for e in editions] == ["en", "fr"]
    assert editions[0]["status"] == "published"


def test_cli_requires_token(
    hub: Hub,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.delenv("DECKDOCK_TOKEN")
    assert main(["publish", str(dist), "--hub", hub.url]) == 1
    assert "DECKDOCK_TOKEN" in capsys.readouterr().err
    assert hub.requests == []


def test_cli_refuses_remote_http(dist: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["publish", str(dist), "--hub", "http://example.com"]) == 1
    assert "https" in capsys.readouterr().err


def test_cli_no_edition(tmp_path: Path, hub: Hub, capsys: pytest.CaptureFixture[str]):
    assert main(["publish", str(tmp_path), "--hub", hub.url]) == 1
    assert "No edition found" in capsys.readouterr().err
    assert hub.requests == []


def test_cli_stops_at_first_failed_edition(
    dist: Path, capsys: pytest.CaptureFixture[str]
):
    failing = Hub(statuses=[422])
    try:
        assert main(["publish", str(dist), "--hub", failing.url]) == 1
        assert len(failing.requests) == 1
        assert "notes[0]: bad" in capsys.readouterr().err
    finally:
        failing.close()


def test_token_never_printed(hub: Hub, dist: Path, capsys: pytest.CaptureFixture[str]):
    _ = main(["publish", str(dist), "--hub", hub.url])
    _ = main(["publish", str(dist), "--hub", "http://example.com"])
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
