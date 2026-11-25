"""Tests for action/publish.py, against a fake hub on 127.0.0.1."""

import io
import json
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

PUBLISH = Path(__file__).resolve().parent.parent / "publish.py"
TOKEN = "s3cr3t-token-value"


class Hub:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {
            "status": "published", "version": "v1", "notes": 3,
            "warnings": [], "errors": [],
        }
        self.requests = []
        self.redirect_to = None
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                hub.requests.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "ctype": self.headers.get("Content-Type"),
                    "body": self.rfile.read(length),
                })
                if hub.redirect_to:
                    self.send_response(302)
                    self.send_header("Location", hub.redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps(hub.body).encode()
                self.send_response(hub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def hub():
    h = Hub()
    yield h
    h.close()


@pytest.fixture
def dist(tmp_path):
    for edition in ("en", "fr"):
        (tmp_path / edition / "media").mkdir(parents=True)
        (tmp_path / edition / "deck.json").write_text('{"edition": "%s"}' % edition)
        (tmp_path / edition / "media" / "x.png").write_bytes(b"png")
    (tmp_path / "index.json").write_text("{}")  # not an edition
    return tmp_path


def run(dist, hub_url, token=TOKEN):
    env = {"DECKDOCK_PATH": str(dist)}
    if hub_url is not None:
        env["DECKDOCK_HUB_URL"] = hub_url
    if token is not None:
        env["DECKDOCK_TOKEN"] = token
    return subprocess.run(
        [sys.executable, str(PUBLISH)], env=env, capture_output=True, text=True
    )


def test_publish_posts_each_edition(hub, dist):
    result = run(dist, hub.url + "/")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(r["path"] for r in hub.requests) == ["/api/publish/en", "/api/publish/fr"]
    for r in hub.requests:
        assert r["auth"] == f"Bearer {TOKEN}"
        assert r["ctype"] == "application/gzip"
        with tarfile.open(fileobj=io.BytesIO(r["body"]), mode="r:gz") as tar:
            assert sorted(tar.getnames()) == ["deck.json", "media/x.png"]


def test_publish_fails_with_hub_errors(dist):
    h = Hub(422, {"errors": [
        {"where": "cards[0]", "message": "bad one"},
        {"where": "cards[1]", "message": "bad two"},
    ]})
    try:
        result = run(dist, h.url)
    finally:
        h.close()
    assert result.returncode != 0
    lines = [l for l in result.stdout.splitlines() if l.startswith("::error::")]
    assert lines == ["::error::cards[0]: bad one", "::error::cards[1]: bad two"]
    assert len(h.requests) == 1  # stops at the first failed edition


def test_publish_requires_token_and_hub_url(hub, dist):
    no_token = run(dist, hub.url, token=None)
    assert no_token.returncode != 0
    assert "::error::" in no_token.stdout and "DECKDOCK_TOKEN" in no_token.stdout
    no_url = run(dist, None)
    assert no_url.returncode != 0
    assert "::error::" in no_url.stdout and "hub-url" in no_url.stdout
    assert hub.requests == []


def test_publish_never_prints_token(dist):
    h = Hub(500, {"detail": "boom"})
    try:
        failed = run(dist, h.url)
        h.status, h.body = 200, {"status": "published", "version": "v", "notes": 1}
        fine = run(dist, h.url)
    finally:
        h.close()
    refused = run(dist, "http://example.com")
    unreachable = run(dist, "http://127.0.0.1:1")
    for r in (failed, fine, refused, unreachable):
        assert TOKEN not in r.stdout + r.stderr
    assert failed.returncode != 0 and "500" in failed.stdout
    assert unreachable.returncode != 0 and "::error::" in unreachable.stdout


def test_publish_refuses_plain_http_for_remote_host(hub, dist):
    result = run(dist, "http://hub.example.com")
    assert result.returncode != 0
    assert "https" in result.stdout
    assert hub.requests == []


def test_publish_refuses_redirects(dist):
    h = Hub()
    h.redirect_to = "/elsewhere"
    try:
        result = run(dist, h.url)
    finally:
        h.close()
    assert result.returncode != 0
    assert "302" in result.stdout and "::error::" in result.stdout
    assert "elsewhere" not in result.stdout
    assert len(h.requests) == 1  # the redirect target was never requested
    assert TOKEN not in result.stdout + result.stderr


def test_publish_escapes_hub_messages(dist):
    evil = "x\r\n::set-output name=pwn::1 100%"
    h = Hub(422, {"errors": [{"where": evil, "message": evil}]})
    h2 = Hub(200, {"status": "published", "version": evil, "notes": 1, "warnings": [evil]})
    try:
        bad = run(dist, h.url)
        good = run(dist, h2.url)
    finally:
        h.close()
        h2.close()
    esc = "x%0D%0A::set-output name=pwn::1 100%25"
    assert bad.stdout.splitlines()[0] == f"::error::{esc}: {esc}"
    for out in (bad.stdout, good.stdout):
        assert "\r" not in out
        assert not any(l.lstrip().startswith("::set-output") for l in out.splitlines())
    assert f"::warning::en: {esc}" in good.stdout


@pytest.mark.parametrize("body", [
    {"errors": "oops"},
    {"errors": ["a string", 3]},
    {"errors": None},
    {"errors": {"where": "w"}},
])
def test_publish_tolerates_malformed_errors(dist, body):
    h = Hub(422, body)
    try:
        result = run(dist, h.url)
    finally:
        h.close()
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "::error::en: hub responded with HTTP 422" in result.stdout


def test_publish_tolerates_malformed_warnings(dist):
    h = Hub(200, {"status": "published", "version": "v", "notes": 1, "warnings": "careful"})
    try:
        result = run(dist, h.url)
    finally:
        h.close()
    assert result.returncode == 0 and "Traceback" not in result.stderr
