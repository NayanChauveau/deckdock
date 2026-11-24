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


def test_help_lists_the_four_commands(capsys: pytest.CaptureFixture[str]):
    assert main([]) == 0
    out = capsys.readouterr().out
    for command in ("init", "validate", "build", "check"):
        assert command in out
    assert "not implemented" not in out
