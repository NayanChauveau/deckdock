# deckdock

deckdock defines `deckdock/1`, a JSON format for Anki decks that can be
published, checked and imported, and ships its reference checker: the format plus
a verifier. It does not compile decks itself; to write one from YAML, start from
[deckdock-template](https://github.com/NayanChauveau/deckdock-template).

## Layout

- `cli/` - the `deckdock` checker and Python library (standard library only, MIT).
- `spec/` - the `deckdock/1` format ([`deckdock-1.md`](spec/deckdock-1.md)), its JSON Schema
  and examples (MIT).
- `action/` - a composite GitHub Action that runs `deckdock check` (MIT).
- `addon/` - the DeckDock Anki add-on, with an embedded copy of the library (AGPL-3.0-or-later).
- `hub/` - added later (AGPL-3.0-or-later).

## Usage

Run the checker without installing it (needs [uv](https://docs.astral.sh/uv/)):

```sh
uvx --from git+https://github.com/NayanChauveau/deckdock@v0#subdirectory=cli deckdock check dist
```

| Command | What it does |
| --- | --- |
| `deckdock check [DIST]` | Check compiled editions (`DIST/<edition>/deck.json` and `media/`) against `deckdock/1` (default `dist`). |
| `deckdock --version` | Show the version. |

Errors are printed as `<path>: <JSON path>: <message>`; the exit code is 1 on error, 0 otherwise.

### GitHub Action

```yaml
- uses: NayanChauveau/deckdock/action@v0
  with:
    path: dist
```

See [`action/README.md`](action/README.md). To publish a deck to the DeckDock hub from CI, see
[Publish to the DeckDock hub](docs/publish-to-the-hub.md).

### Writing a compiler

Any tool can produce `deckdock/1`. See "Writing your own compiler" in
[`spec/deckdock-1.md`](spec/deckdock-1.md). [deckdock-template](https://github.com/NayanChauveau/deckdock-template)
is a ready-made deck repository and example compiler (YAML to `deckdock/1`); it depends on the
`deckdock` Python library (`deckdock.format`, `deckdock.guid`, `deckdock.issues`).

## Development

From `cli/`:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

## License

MIT for `spec/`, `cli/` and `action/`; see `LICENSE-MIT`.
