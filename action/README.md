# DeckDock GitHub Action

Runs the [DeckDock](../README.md) CLI in a workflow: validate a deck repository, build it into the `deckdock/1` format, or check a built `dist/`.

## Usage

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set deck version
        run: echo "DECKDOCK_VERSION=$(date -u +%Y-%m-%dT%H:%M:%SZ)+${GITHUB_SHA::7}" >> "$GITHUB_ENV"

      - uses: NayanChauveau/deckdock/action@v1
        with:
          command: build

      - uses: actions/upload-artifact@v4
        with:
          name: deck
          path: dist/
```

`build` reads the `DECKDOCK_VERSION` environment variable (default `dev`).

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `command` | `build` | `validate`, `build` or `check`. |
| `path` | `.` | Deck repository root. |
| `deckdock-ref` | empty | Git ref of the DeckDock repository to install the CLI from. Empty means the ref the action was called with (`@v1`). `local` installs the CLI from the checkout containing this action (used by the monorepo CI). |

## How `command` and `path` map to the CLI

| `command` | Runs |
| --- | --- |
| `validate` | `deckdock validate <path>` |
| `build` | `deckdock build <path>` (output goes to `<path>/dist`) |
| `check` | `deckdock check <path>/dist` |

## Pinning

Reference the action with a major tag (`@v1`) to get compatible updates, or with a full tag or commit SHA for fully reproducible builds. The CLI is installed from the same ref as the action, so the action and the CLI always match. If the ref cannot be determined and `deckdock-ref` is not set, the action fails rather than installing an unpinned version.
