"""Tests for the 4-folder document organizer."""
from pathlib import Path

from three_surgeons.core.doc_organizer import (
    FOLDERS,
    DetectedProject,
    init_docs,
    scan_repo,
)


def test_init_docs_creates_all_folders(tmp_path: Path) -> None:
    result = init_docs(tmp_path)

    for folder in FOLDERS:
        folder_path = tmp_path / "docs" / folder
        assert folder_path.is_dir(), f"docs/{folder}/ not created"
        readme = folder_path / "README.md"
        assert readme.exists(), f"docs/{folder}/README.md not created"
        assert len(readme.read_text()) > 20

    assert set(result.folders_created) == set(FOLDERS)
    assert result.already_existed == []


def test_init_docs_updates_gitignore(tmp_path: Path) -> None:
    result = init_docs(tmp_path)

    assert result.gitignore_updated is True
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "docs/inbox/" in gitignore
    assert "docs/vision/" in gitignore
    assert "docs/reflect/" in gitignore
    assert "docs/dao/" in gitignore


def test_init_docs_idempotent(tmp_path: Path) -> None:
    init_docs(tmp_path)
    result2 = init_docs(tmp_path)

    # Second run: folders already exist, gitignore already has entries
    assert set(result2.already_existed) == set(FOLDERS)
    assert result2.folders_created == []
    assert result2.gitignore_updated is False


def test_init_docs_appends_to_existing_gitignore(tmp_path: Path) -> None:
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_text("node_modules/\n.env\n")

    result = init_docs(tmp_path)

    assert result.gitignore_updated is True
    content = gitignore_path.read_text()
    assert "node_modules/" in content  # preserved
    assert "docs/inbox/" in content    # added


def test_init_docs_skip_gitignore(tmp_path: Path) -> None:
    result = init_docs(tmp_path, update_gitignore=False)

    assert result.gitignore_updated is False
    assert not (tmp_path / ".gitignore").exists()


def test_scan_empty_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = scan_repo(tmp_path)

    assert result.projects == []
    assert result.is_superrepo is False


def test_scan_detects_submodules(tmp_path: Path) -> None:
    # Create .gitmodules
    (tmp_path / ".gitmodules").write_text(
        '[submodule "my-plugin"]\n'
        '    path = my-plugin\n'
        '    url = https://github.com/example/my-plugin.git\n'
    )
    # Create the submodule dir with independence signals
    plugin_dir = tmp_path / "my-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "README.md").write_text("# My Plugin")
    (plugin_dir / "pyproject.toml").write_text("[project]\nname = 'test'")
    (plugin_dir / "tests").mkdir()

    result = scan_repo(tmp_path)

    assert result.is_superrepo is True
    assert len(result.projects) == 1
    assert result.projects[0].name == "my-plugin"
    assert result.projects[0].is_submodule is True
    assert result.projects[0].recommended is True


def test_scan_detects_monorepo_packages(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    # Create packages/api with signals
    api_dir = tmp_path / "packages" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "README.md").write_text("# API")
    (api_dir / "package.json").write_text("{}")

    # Create packages/shared with only one signal (should not recommend)
    shared_dir = tmp_path / "packages" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "package.json").write_text("{}")

    result = scan_repo(tmp_path)

    names = {p.name: p for p in result.projects}
    assert "api" in names
    assert names["api"].score >= 2
    # shared has score 1, not recommended
    if "shared" in names:
        assert not names["shared"].recommended


def test_detected_project_score() -> None:
    p = DetectedProject(
        path=Path("/tmp/test"),
        name="test",
        reason="test",
        has_readme=True,
        has_package_manifest=True,
        has_tests=True,
        is_submodule=False,
    )
    assert p.score == 3
    assert p.recommended is True

    p2 = DetectedProject(
        path=Path("/tmp/test"),
        name="test",
        reason="test",
        has_readme=True,
        has_package_manifest=False,
        has_tests=False,
        is_submodule=False,
    )
    assert p2.score == 1
    assert p2.recommended is False
