import pytest

from deckdock.issues import Issue, print_issues


def test_issue_format_with_and_without_line():
    assert str(Issue("cards/a.yaml", "boom", 12)) == "cards/a.yaml:12: boom"
    assert str(Issue("deckdock.yaml", "boom")) == "deckdock.yaml: boom"


def test_print_issues_returns_exit_code(capsys: pytest.CaptureFixture[str]):
    assert print_issues([]) == 0
    assert print_issues([Issue("a", "b", 1)]) == 1
    assert "a:1: b" in capsys.readouterr().err
