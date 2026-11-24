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
