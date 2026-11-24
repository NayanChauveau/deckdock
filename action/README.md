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
| `command` | `check` | The DeckDock command to run. Only `check` is supported; anything else fails with an error. |
| `path` | `dist` | Compiled dist folder (contains `<edition>/deck.json`). |
| `deckdock-ref` | empty | Git ref of the DeckDock repository to install the CLI from. Empty means the ref the action was called with (`@v2`). `local` installs the CLI from the checkout containing this action (used by the monorepo CI). |

## What it runs

`deckdock check <path>`, in strict mode.

## Pinning

Reference the action with a major tag (`@v2`) to get compatible updates, or with a full tag or commit SHA for fully reproducible builds. The CLI is installed from the same ref as the action, so the action and the CLI always match. If the ref cannot be determined and `deckdock-ref` is not set, the action fails rather than installing an unpinned version.
