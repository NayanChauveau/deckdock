import copy
import hashlib
import json
import pathlib
from typing import cast

import pytest

from deckdock.cli import main
from deckdock.format import check as check_module
from deckdock.format import check_deck, check_dist

Deck = dict[str, object]

SPEC = pathlib.Path(__file__).parents[2] / "spec"


def minimal() -> Deck:
    return cast(Deck, json.loads((SPEC / "examples/valid/minimal.json").read_text()))


def messages(data: object) -> str:
    return "\n".join(issue.message for issue in check_deck(data))


def write_dist(
    tmp_path: pathlib.Path, data: Deck, files: dict[str, bytes] | None = None, edition: str = "en"
) -> pathlib.Path:
    dist = tmp_path / "dist"
    (dist / edition / "media").mkdir(parents=True)
    _ = (dist / edition / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    for name, content in (files or {}).items():
        _ = (dist / edition / "media" / name).write_bytes(content)
    return dist


def with_media(data: Deck, name: str, content: bytes) -> Deck:
    data["media"] = [{"filename": name, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}]
    return data


def first_note(data: Deck) -> dict[str, object]:
    return cast(list[dict[str, object]], data["notes"])[0]


def test_minimal_is_valid():
    assert check_deck(minimal()) == []


def test_top_level_must_be_an_object():
    assert "must be an object" in messages([])


def test_unknown_top_level_key():
    data = minimal()
    data["extra"] = 1
    assert "unknown key 'extra'" in messages(data)


def test_wrong_format_version():
    data = minimal()
    data["format"] = "deckdock/2"
    assert "format must be 'deckdock/1'" in messages(data)


def test_duplicate_guid():
    data = minimal()
    notes = cast(list[object], data["notes"])
    notes.append(copy.deepcopy(notes[0]))
    assert "duplicate guid" in messages(data)


def test_note_fields_must_match_notetype():
    data = minimal()
    fields = cast(dict[str, str], first_note(data)["fields"])
    del fields["Back"]
    fields["Verso"] = "x"
    text = messages(data)
    assert "missing field 'Back'" in text
    assert "unknown field 'Verso'" in text


def test_cloze_notetype_has_one_template():
    data = minimal()
    notetype = cast(list[dict[str, object]], data["notetypes"])[0]
    notetype["kind"] = "cloze"
    templates = cast(list[object], notetype["templates"])
    templates.append(copy.deepcopy(templates[0]))
    assert "exactly one template" in messages(data)


@pytest.mark.parametrize("language", ["fr", [], [1]])
def test_language_must_be_non_empty_list(language: object):
    data = minimal()
    cast(Deck, data["deck"])["language"] = language
    assert "language" in messages(data)


@pytest.mark.parametrize("options", [{"extra": 1}, {"new_per_day": -1}, {"new_per_day": True}, []])
def test_options_keys_and_values(options: object):
    data = minimal()
    cast(Deck, data["deck"])["options"] = options
    assert "options" in messages(data)


def test_deck_path_segments():
    data = minimal()
    first_note(data)["deck"] = "A::::B"
    assert "deck path" in messages(data)


def test_media_filename_with_slash():
    data = minimal()
    data["media"] = [{"filename": "a/b.png", "sha256": "0" * 64, "size": 1}]
    assert "filename" in messages(data)


def test_too_many_notes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(check_module, "MAX_NOTES", 1)
    data = minimal()
    notes = cast(list[dict[str, object]], data["notes"])
    second = copy.deepcopy(notes[0])
    second["guid"] = "other"
    notes.append(second)
    assert "too many notes" in messages(data)


def test_check_dist_valid(tmp_path: pathlib.Path):
    data = first_valid_with_image()
    dist = write_dist(tmp_path, data, {"x.png": b"png"})
    assert check_dist(dist) == []


def first_valid_with_image() -> Deck:
    data = with_media(minimal(), "x.png", b"png")
    cast(dict[str, str], first_note(data)["fields"])["Front"] = '<img src="x.png">'
    return data


def test_check_dist_media_sha_mismatch(tmp_path: pathlib.Path):
    dist = write_dist(tmp_path, with_media(minimal(), "x.png", b"png"), {"x.png": b"PNG"})
    issues = check_dist(dist)
    assert any("sha256 mismatch" in i.message for i in issues)
    assert not any("size mismatch" in i.message for i in issues)


def test_check_dist_media_size_mismatch(tmp_path: pathlib.Path):
    data = with_media(minimal(), "x.png", b"png")
    cast(list[dict[str, object]], data["media"])[0]["size"] = 99
    issues = check_dist(write_dist(tmp_path, data, {"x.png": b"png"}))
    assert any("size mismatch" in i.message for i in issues)


def test_check_dist_unlisted_and_missing_media(tmp_path: pathlib.Path):
    dist = write_dist(tmp_path, with_media(minimal(), "listed.png", b"a"), {"stray.png": b"b"})
    text = "\n".join(i.message for i in check_dist(dist))
    assert "not listed" in text
    assert "missing file" in text


def test_check_dist_unlisted_reference(tmp_path: pathlib.Path):
    data = minimal()
    cast(dict[str, str], first_note(data)["fields"])["Front"] = '<img src="x.png">'
    issues = check_dist(write_dist(tmp_path, data))
    assert any("references unlisted media 'x.png'" in i.message for i in issues)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("<img src='a.png'>", "a.png"),
        ("[sound:a.mp3]", "a.mp3"),
        ("<style>.x{background:url(a.png)}</style>", "a.png"),
        ('<style>.x{background:url("a b.png")}</style>', "a b.png"),
    ],
)
def test_reference_patterns(tmp_path: pathlib.Path, text: str, name: str):
    data = minimal()
    cast(dict[str, str], first_note(data)["fields"])["Front"] = text
    issues = check_dist(write_dist(tmp_path, data))
    assert any(f"references unlisted media '{name}'" in i.message for i in issues)


def test_references_in_templates_and_css(tmp_path: pathlib.Path):
    data = minimal()
    notetype = cast(list[dict[str, object]], data["notetypes"])[0]
    notetype["css"] = ".a { background: url(bg.png) }"
    cast(list[dict[str, str]], notetype["templates"])[0]["front"] = '{{Front}}<img src="t.png">'
    text = "\n".join(i.message for i in check_dist(write_dist(tmp_path, data)))
    assert "references unlisted media 'bg.png'" in text
    assert "references unlisted media 't.png'" in text


def test_external_and_data_urls_ignored(tmp_path: pathlib.Path):
    data = minimal()
    cast(dict[str, str], first_note(data)["fields"])["Front"] = (
        '<img src="https://example.com/a.png"><img src="data:image/png;base64,AAAA">'
        '<img src="sub/a.png"><img src="{{Front}}">'
    )
    assert check_dist(write_dist(tmp_path, data)) == []


def test_check_dist_no_editions(tmp_path: pathlib.Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    issues = check_dist(dist)
    assert [i.message for i in issues] == ["no editions found"]
    assert issues[0].path == str(dist)


def test_check_dist_not_a_directory(tmp_path: pathlib.Path):
    issues = check_dist(tmp_path / "missing")
    assert [i.message for i in issues] == ["not a directory"]


def test_check_dist_invalid_json(tmp_path: pathlib.Path):
    dist = write_dist(tmp_path, minimal())
    _ = (dist / "en" / "deck.json").write_text("{not json", encoding="utf-8")
    issues = check_dist(dist)
    assert len(issues) == 1
    assert "invalid JSON" in issues[0].message


def test_check_dist_issue_path_and_json_path(tmp_path: pathlib.Path):
    data = minimal()
    del cast(dict[str, str], first_note(data)["fields"])["Back"]
    issues = check_dist(write_dist(tmp_path, data))
    assert [str(i) for i in issues] == ["dist/en/deck.json: notes[0].fields: missing field 'Back'"]


def test_check_dist_checks_every_edition(tmp_path: pathlib.Path):
    dist = write_dist(tmp_path, minimal(), edition="en")
    other = minimal()
    other["extra"] = 1
    (dist / "fr").mkdir()
    _ = (dist / "fr" / "deck.json").write_text(json.dumps(other), encoding="utf-8")
    issues = check_dist(dist)
    assert [i.path for i in issues] == ["dist/fr/deck.json"]


def test_cli_check_exit_codes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    good = write_dist(tmp_path / "good", minimal())
    assert main(["check", str(good)]) == 0
    assert capsys.readouterr().err == ""
    bad_data = minimal()
    bad_data["extra"] = 1
    bad = write_dist(tmp_path / "bad", bad_data)
    assert main(["check", str(bad)]) == 1
    assert "unknown key 'extra'" in capsys.readouterr().err


def test_cli_check_defaults_to_dist(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    _ = write_dist(tmp_path, minimal())
    monkeypatch.chdir(tmp_path)
    assert main(["check"]) == 0


def test_id_and_sha256_reject_trailing_newline():
    data = minimal()
    cast(Deck, data["deck"])["id"] = "hello-deck\n"
    assert "deck.id" in messages(data)
    data = minimal()
    data["media"] = [{"filename": "a.png", "sha256": "0" * 64 + "\n", "size": 1}]
    assert "sha256" in messages(data)


def test_strict_flag_controls_unknown_keys():
    data = minimal()
    data["extra"] = 1
    cast(Deck, data["deck"])["options"] = {"new_per_day": 1, "extra": 2}
    first_note(data)["extra"] = 3
    assert check_deck(data) != []
    assert check_deck(data, strict=False) == []


def test_non_strict_still_enforces_other_rules():
    data = minimal()
    data["extra"] = 1
    first_note(data)["guid"] = ""
    assert check_deck(data, strict=False) != []


def test_check_dist_strict_flag(tmp_path: pathlib.Path):
    data = minimal()
    data["extra"] = 1
    dist = write_dist(tmp_path, data)
    assert check_dist(dist) != []
    assert check_dist(dist, strict=False) == []


@pytest.mark.parametrize(
    ("filename", "text"),
    [("a&b.png", '<img src="a&amp;b.png">'), ("a b.png", '<img src="a%20b.png">'), ("a b.png", '<img src="a b.png">')],
)
def test_references_are_unescaped_and_unquoted(tmp_path: pathlib.Path, filename: str, text: str):
    data = with_media(minimal(), filename, b"x")
    cast(dict[str, str], first_note(data)["fields"])["Front"] = text
    assert check_dist(write_dist(tmp_path, data, {filename: b"x"})) == []


def test_check_dist_unreadable_media_is_an_issue(tmp_path: pathlib.Path):
    data = with_media(minimal(), "x.png", b"png")
    dist = write_dist(tmp_path, data)
    (dist / "en" / "media" / "x.png").mkdir()
    issues = check_dist(dist)
    assert any("x.png" in i.message for i in issues)


def test_check_dist_unreadable_media_file(tmp_path: pathlib.Path):
    data = with_media(minimal(), "x.png", b"png")
    dist = write_dist(tmp_path, data, {"x.png": b"png"})
    target = dist / "en" / "media" / "x.png"
    target.chmod(0)
    try:
        issues = check_dist(dist)
    finally:
        target.chmod(0o644)
    assert any("cannot read" in i.message for i in issues)


@pytest.mark.parametrize("edition", ["", ".", "..", "a/b", "a\\b"])
def test_edition_must_not_be_a_path(edition: str):
    data = minimal()
    cast(Deck, data["deck"])["edition"] = edition
    assert "edition" in messages(data)


def test_edition_must_match_directory(tmp_path: pathlib.Path):
    dist = write_dist(tmp_path, minimal(), edition="fr")
    issues = check_dist(dist)
    assert [i.message for i in issues] == ["deck.edition 'en' does not match directory 'fr'"]
