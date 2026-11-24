# deckdock

deckdock is a toolchain that compiles Anki decks written as YAML into a
JSON format (`deckdock/1`) that can be published, checked and imported.

## Layout

- `cli/` - the `deckdock` command-line tool (Python, MIT).
- `spec/` - the `deckdock/1` compiled format ([`deckdock-1.md`](spec/deckdock-1.md)), the
  source format ([`deckdock-source-1.md`](spec/deckdock-source-1.md)), JSON Schemas and
  examples (MIT).
- `action/` - a composite GitHub Action that runs the CLI in a deck repository (MIT).
- `hub/` and `addon/` - added later (AGPL-3.0-or-later).

## Usage

Run the CLI without installing it (needs [uv](https://docs.astral.sh/uv/)):

```sh
uvx --from git+https://github.com/NayanChauveau/deckdock@v1#subdirectory=cli deckdock <command>
```

| Command | What it does |
| --- | --- |
| `deckdock init [DIR]` | Create a Hello World deck project in `DIR` (default `.`). |
| `deckdock validate [ROOT]` | Check the YAML sources of the project in `ROOT`. |
| `deckdock build [ROOT] [--out DIR]` | Compile every edition into `DIR/<edition>/deck.json` and `media/` (default `ROOT/dist`). |
| `deckdock check [DIST]` | Check compiled editions against `deckdock/1` (default `dist`). |

Errors are printed as `<path>:<line>: <message>`; the exit code is 1 on error, 0 otherwise.
A ready-made deck repository lives at
[NayanChauveau/deckdock-template](https://github.com/NayanChauveau/deckdock-template).

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
