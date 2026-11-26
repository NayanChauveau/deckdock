import copy
import json
import pathlib
import subprocess
import sys
from typing import cast

import pytest

from deckdock import __version__
from deckdock.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"deckdock {__version__}"


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        _ = main(["frobnicate"])
    assert exc.value.code == 2


def test_help_lists_only_check(capsys: pytest.CaptureFixture[str]):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "check" in out
    for removed in ("init", "validate", "build"):
        assert removed not in out


@pytest.mark.parametrize("command", ["init", "validate", "build"])
def test_removed_commands_exit_2(command: str):
    with pytest.raises(SystemExit) as exc:
        _ = main([command])
    assert exc.value.code == 2


def _write_deck(tmp_path: pathlib.Path, data: object) -> pathlib.Path:
    dist = tmp_path / "dist"
    (dist / "en" / "media").mkdir(parents=True)
    _ = (dist / "en" / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    return dist


def _minimal() -> dict[str, object]:
    path = pathlib.Path(__file__).parents[2] / "spec/examples/valid/minimal.json"
    return cast(dict[str, object], json.loads(path.read_text()))


def test_check_non_strict_accepts_unknown_key(tmp_path: pathlib.Path):
    data = _minimal()
    data["extra"] = 1
    dist = _write_deck(tmp_path, data)
    assert main(["check", str(dist)]) == 1
    assert main(["check", str(dist), "--non-strict"]) == 0


def test_check_json_output(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    good = _write_deck(tmp_path, _minimal())
    assert main(["check", str(good), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "issues": []}

    data = _minimal()
    data["extra"] = 1
    bad = _write_deck(tmp_path / "bad", data)
    assert main(["check", str(bad), "--json"]) == 1
    report = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert report["ok"] is False
    assert report["issues"] == [
        {
            "path": "dist/en/deck.json",
            "where": "",
            "message": "unknown key 'extra'",
            "line": None,
        }
    ]


def test_python_dash_m_deckdock():
    result = subprocess.run(
        [sys.executable, "-m", "deckdock", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"deckdock {__version__}"


def _compat_files(tmp_path: pathlib.Path, previous: object, new: object) -> list[str]:
    a = tmp_path / "previous.json"
    b = tmp_path / "new.json"
    _ = a.write_text(json.dumps(previous), encoding="utf-8")
    _ = b.write_text(json.dumps(new), encoding="utf-8")
    return [str(a), str(b)]


def test_compat_command(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    previous = _minimal()
    new = copy.deepcopy(previous)
    nt = cast(list[dict[str, list[str]]], new["notetypes"])[0]
    nt["fields"].append("Extra")
    for note in cast(list[dict[str, dict[str, str]]], new["notes"]):
        note["fields"]["Extra"] = ""
    files = _compat_files(tmp_path, previous, new)
    assert main(["compat", *files, "--json"]) == 0
    changes = cast(list[dict[str, str]], json.loads(capsys.readouterr().out))
    assert [c["kind"] for c in changes] == ["appended_fields"]

    nt["fields"] = nt["fields"][1:]
    for note in cast(list[dict[str, dict[str, str]]], new["notes"]):
        del note["fields"][next(iter(note["fields"]))]
    assert main(["compat", *_compat_files(tmp_path, previous, new)]) == 1
    assert "breaking" in capsys.readouterr().out
