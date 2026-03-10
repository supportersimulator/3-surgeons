# tests/test_skill_registration.py
"""Tests for skill registration via symlinks."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from three_surgeons.core.skill_registration import (
    SkillRegistrar,
    RegistrationResult,
    detect_install_mode,
)


class TestDetectInstallMode:
    def test_submodule_detected(self, tmp_path: Path) -> None:
        """Detects submodule install when .git is a file (gitlink)."""
        (tmp_path / ".git").write_text("gitdir: ../../.git/modules/3-surgeons\n")
        mode = detect_install_mode(tmp_path)
        assert mode == "submodule"

    def test_standalone_detected(self, tmp_path: Path) -> None:
        """Detects standalone install when .git is a directory."""
        (tmp_path / ".git").mkdir()
        mode = detect_install_mode(tmp_path)
        assert mode == "standalone"

    def test_marketplace_detected(self, tmp_path: Path) -> None:
        """Detects marketplace install when inside plugins directory."""
        plugins_dir = tmp_path / ".claude" / "plugins" / "3-surgeons"
        plugins_dir.mkdir(parents=True)
        mode = detect_install_mode(plugins_dir)
        assert mode == "marketplace"

    def test_unknown_fallback(self, tmp_path: Path) -> None:
        mode = detect_install_mode(tmp_path)
        assert mode == "unknown"


class TestSkillRegistrar:
    def test_discover_skills(self, tmp_path: Path) -> None:
        """Discovers all skills with SKILL.md files."""
        skills_dir = tmp_path / "skills"
        for name in ["probe", "consensus", "sentinel"]:
            skill_path = skills_dir / name
            skill_path.mkdir(parents=True)
            (skill_path / "SKILL.md").write_text(f"# {name}\n")

        registrar = SkillRegistrar(plugin_root=tmp_path)
        skills = registrar.discover_skills()
        assert len(skills) == 3
        assert "probe" in skills

    def test_create_symlinks(self, tmp_path: Path) -> None:
        """Creates symlinks from target dir to skill dirs."""
        # Setup source skills
        skills_dir = tmp_path / "source" / "skills"
        for name in ["probe", "sentinel"]:
            s = skills_dir / name
            s.mkdir(parents=True)
            (s / "SKILL.md").write_text(f"# {name}\n")

        target_dir = tmp_path / "target" / "skills"
        registrar = SkillRegistrar(plugin_root=tmp_path / "source")
        result = registrar.create_symlinks(target_dir)
        assert result.registered == 2
        assert result.failed == 0
        assert (target_dir / "probe").is_symlink()
        assert (target_dir / "sentinel").is_symlink()

    def test_broken_symlink_detected(self, tmp_path: Path) -> None:
        """Detects and flags broken symlinks."""
        target_dir = tmp_path / "target" / "skills"
        target_dir.mkdir(parents=True)
        broken = target_dir / "dead-skill"
        broken.symlink_to(tmp_path / "nonexistent")

        registrar = SkillRegistrar(plugin_root=tmp_path)
        broken_links = registrar.check_symlink_health(target_dir)
        assert len(broken_links) == 1
        assert "dead-skill" in broken_links[0]

    def test_revert_removes_symlinks_only(self, tmp_path: Path) -> None:
        """Revert removes symlinks but not regular files."""
        target_dir = tmp_path / "target" / "skills"
        target_dir.mkdir(parents=True)

        # Create a symlink and a regular file
        (target_dir / "real-file.md").write_text("keep me")
        link = target_dir / "linked-skill"
        link.symlink_to(tmp_path)

        registrar = SkillRegistrar(plugin_root=tmp_path)
        removed = registrar.revert_symlinks(target_dir)
        assert removed == 1
        assert not link.exists()
        assert (target_dir / "real-file.md").exists()
