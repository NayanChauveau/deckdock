# deckdock

deckdock is a toolchain that compiles Anki decks written as YAML into a
JSON format (`deckdock/1`) that can be published, checked and imported.

## Layout

- `cli/` - the `deckdock` command-line tool (Python, MIT).
- `spec/` - the `deckdock/1` format specification and JSON Schemas (MIT).
- `action/` - a composite GitHub Action that builds a deck (MIT).
- `hub/` and `addon/` - added later (AGPL-3.0-or-later).

## Development

From `cli/`:

```sh
uv run pytest
uv run ruff check .
uv run basedpyright
```

## Specification

See [`spec/deckdock-1.md`](spec/deckdock-1.md) for the compiled format (added in a later task).

## License

MIT for `spec/`, `cli/` and `action/`; see `LICENSE-MIT`.
