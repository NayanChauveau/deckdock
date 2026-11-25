# DeckDock GitHub Action

Runs the [DeckDock](../README.md) reference checker in a workflow: checks a compiled `dist/` against the `deckdock/1` format. The step fails if any error is found.

The Action does not compile anything. Compile your deck with your own tool (for example [deckdock-template](https://github.com/NayanChauveau/deckdock-template)), then check the output.

## Usage

```yaml
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ... compile your deck into dist/<edition>/deck.json here ...

      - uses: NayanChauveau/deckdock/action@v2
        with:
          path: dist
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `command` | `check` | The DeckDock command to run. `check` or `publish`; anything else fails with an error. |
| `path` | `dist` | Compiled dist folder (contains `<edition>/deck.json`). |
| `hub-url` | empty | Base URL of the DeckDock hub. Required for `publish` (no default). A trailing `/` is ignored. |
| `deckdock-ref` | empty | Git ref of the DeckDock repository to install the CLI from. Empty means the ref the action was called with (`@v2`). `local` installs the CLI from the checkout containing this action (used by the monorepo CI). |

## What it runs

`check`: `deckdock check <path>`, in strict mode.

`publish`: uploads each edition to the hub (see below). It runs `publish.py`, which uses only the Python standard library, so it installs nothing.

## Publishing to a hub

```yaml
      - uses: NayanChauveau/deckdock/action@v2
        with:
          command: publish
          path: dist
          hub-url: ${{ vars.DECKDOCK_HUB_URL }}
        env:
          DECKDOCK_TOKEN: ${{ secrets.DECKDOCK_TOKEN }}
```

`DECKDOCK_TOKEN` (the per-deck token, from a secret) and `hub-url` are both required; the step fails without them.

For every `<path>/<edition>/` folder that contains a `deck.json`, the action builds a `tar.gz` of that folder and sends `POST <hub-url>/api/publish/<edition>` with `Authorization: Bearer $DECKDOCK_TOKEN` and `Content-Type: application/gzip`. Archive members are relative to the edition folder, so the hub sees `deck.json` and `media/...` at the archive root (no leading folder).

The hub answers with JSON `{"status": "published" | "already_published" | "pending_review", "version", "notes", "warnings", "errors": [{"where", "message"}]}`. The action prints one summary line per edition, reports each warning with `::warning::`, and fails the step on any response with HTTP status 400 or above, reporting each error as `::error::where: message` (or one error with the HTTP status when the body is not JSON).

Editions are published in alphabetical order, and the action stops at the first edition that fails: the following ones would most likely fail for the same reason (bad token, wrong URL).

The token is never printed. For the same reason, `hub-url` must be `https`; plain `http` is accepted only for `localhost` and `127.0.0.1` (local testing).

## Pinning

Reference the action with a major tag (`@v2`) to get compatible updates, or with a full tag or commit SHA for fully reproducible builds. The CLI is installed from the same ref as the action, so the action and the CLI always match. If the ref cannot be determined and `deckdock-ref` is not set, the action fails rather than installing an unpinned version.
