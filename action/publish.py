#!/usr/bin/env python3
"""Publish compiled DeckDock editions to a hub. Standard library only.

Configuration comes from the environment (set by action.yml):
  DECKDOCK_HUB_URL  hub base URL (https, or http on localhost)
  DECKDOCK_TOKEN    per-deck bearer token (never printed)
  DECKDOCK_PATH     compiled dist folder (default: dist)

For each <path>/<edition>/ containing deck.json, the edition directory is
archived as tar.gz (members relative to the edition directory: deck.json,
media/...) and POSTed to <hub-url>/api/publish/<edition>. Stops at the first
failed edition.
"""

import io
import json
import os
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def esc(value):
    """Escape a value for a GitHub workflow command line (anti-injection)."""
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: they could forward the bearer token elsewhere."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fail(message):
    print(f"::error::{message}")
    return 1


def build_archive(edition_dir):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(edition_dir.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(edition_dir).as_posix())
    return buf.getvalue()


def check_hub_url(hub_url):
    parts = urllib.parse.urlsplit(hub_url)
    if parts.scheme == "https" and parts.hostname:
        return None
    if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
        return None
    return "hub-url must use https (plain http is only allowed for localhost), so the token is never sent in clear text."


def post(url, token, data):
    """Return (status, body bytes). Never raises on HTTP errors."""
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"},
    )
    try:
        with _OPENER.open(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def publish_edition(base, token, edition, edition_dir):
    url = f"{base}/api/publish/{urllib.parse.quote(edition)}"
    try:
        status, raw = post(url, token, build_archive(edition_dir))
    except (urllib.error.URLError, OSError) as err:
        reason = getattr(err, "reason", err)
        return fail(f"{edition}: could not reach the hub ({type(reason).__name__}).")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        body = None

    if body is None or status >= 400:
        errors = body.get("errors") if body else None
        entries = [e for e in errors if isinstance(e, dict)] if isinstance(errors, list) else []
        if entries:
            for e in entries:
                print(f"::error::{esc(e.get('where', edition))}: {esc(e.get('message', ''))}")
        else:
            print(f"::error::{edition}: hub responded with HTTP {status}")
        return 1

    warnings = body.get("warnings")
    for w in warnings if isinstance(warnings, list) else []:
        print(f"::warning::{edition}: {esc(w)}")
    print(
        f"{edition}: {esc(body.get('status', '?'))} "
        f"(version {esc(body.get('version', '?'))}, {esc(body.get('notes', '?'))} notes)"
    )
    return 0


def main(env=None):
    env = os.environ if env is None else env
    hub_url = (env.get("DECKDOCK_HUB_URL") or "").strip()
    token = env.get("DECKDOCK_TOKEN") or ""
    dist = Path(env.get("DECKDOCK_PATH") or "dist")

    if not hub_url:
        return fail("hub-url is required for the publish command.")
    if not token:
        return fail("DECKDOCK_TOKEN is required for the publish command.")
    problem = check_hub_url(hub_url)
    if problem:
        return fail(problem)

    editions = sorted(p for p in dist.iterdir() if (p / "deck.json").is_file()) if dist.is_dir() else []
    if not editions:
        return fail(f"No edition found in {dist} (expected <edition>/deck.json).")

    base = hub_url.rstrip("/")
    for edition_dir in editions:
        if publish_edition(base, token, edition_dir.name, edition_dir):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
