import json
import re
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest

from deckdock.build.builder import build
from deckdock.cli import main
from deckdock.init import init_project, slugify
from deckdock.source.load import load_project
from deckdock.source.validate import validate_project


def test_init_then_build_is_valid(tmp_path: Path):
    root = tmp_path / "mon-deck"
    init_project(root)
    out = tmp_path / "out"
    assert build(root, out, "dev") == []
    for edition in ("fr", "en"):
        deck = cast(
            dict[str, list[object]],
            json.loads((out / edition / "deck.json").read_text(encoding="utf-8")),
        )
        assert len(deck["notes"]) == 3
        assert len(deck["media"]) == 1


def test_init_sets_deck_id_from_folder(tmp_path: Path):
    root = tmp_path / "mon-deck"
    init_project(root)
    assert "\nid: mon-deck\n" in (root / "deckdock.yaml").read_text(encoding="utf-8")


def test_init_explicit_deck_id(tmp_path: Path):
    init_project(tmp_path / "x", deck_id="chosen")
    assert "\nid: chosen\n" in (tmp_path / "x" / "deckdock.yaml").read_text(encoding="utf-8")


def test_init_refuses_non_empty_dir(tmp_path: Path):
    _ = (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_project(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_init_accepts_existing_empty_dir(tmp_path: Path):
    init_project(tmp_path)
    assert (tmp_path / "deckdock.yaml").is_file()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("My Deck!", "my-deck"), ("--A__b--", "a-b"), ("日本", "my-deck"), ("", "my-deck")],
)
def test_slugify(name: str, expected: str):
    assert slugify(name) == expected


def test_dotfiles_renamed(tmp_path: Path):
    init_project(tmp_path)
    assert (tmp_path / ".github" / "workflows" / "deck.yml").is_file()
    assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "card-problem.yml").is_file()
    assert (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file()
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / ".editorconfig").is_file()
    assert (tmp_path / ".pre-commit-config.yaml").is_file()
    for undotted in ("github", "gitignore", "editorconfig", "pre-commit-config.yaml"):
        assert not (tmp_path / undotted).exists()


def test_claude_md_points_to_agents(tmp_path: Path):
    init_project(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    assert claude.read_text(encoding="utf-8") == (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert claude.is_symlink()


def test_workflow_uses_pinned_action(tmp_path: Path):
    init_project(tmp_path)
    workflow = (tmp_path / ".github" / "workflows" / "deck.yml").read_text(encoding="utf-8")
    assert "NayanChauveau/deckdock/action@v1" in workflow
    assert "secrets." not in "\n".join(
        line for line in workflow.splitlines() if not line.lstrip().startswith("#")
    )


def test_files_are_copied_byte_for_byte(tmp_path: Path):
    init_project(tmp_path)
    scaffold = files("deckdock") / "scaffold"
    for name in ("README.md", "AGENTS.md", "LICENSE", "media/hello.png"):
        assert (tmp_path / name).read_bytes() == (scaffold / name).read_bytes()


def test_cli_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "proj"
    assert main(["init", str(root)]) == 0
    assert (root / "deckdock.yaml").is_file()
    assert main(["init", str(root)]) == 1
    assert "target is not empty" in capsys.readouterr().err


@pytest.mark.parametrize("doc", ["AGENTS.md", "CONTENT_GUIDELINES.md", "README.md"])
def test_doc_card_examples_are_valid(tmp_path: Path, doc: str):
    init_project(tmp_path)
    text = (tmp_path / doc).read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, flags=re.DOTALL)
    assert blocks or doc != "AGENTS.md"
    for i, block in enumerate(blocks):
        _ = (tmp_path / "cards" / f"doc{i}.yaml").write_text("cards:\n" + block, encoding="utf-8")
    project, issues = load_project(tmp_path)
    assert issues == []
    assert project is not None
    assert validate_project(project) == []
