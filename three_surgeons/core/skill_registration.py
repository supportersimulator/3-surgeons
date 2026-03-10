"""Skill registration via symlinks for submodule installs.

Detects install mode (submodule, standalone, marketplace, unknown),
discovers skills on disk, creates/verifies/reverts symlinks to the
host plugin directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


def detect_install_mode(plugin_root: Path) -> str:
    """Detect how 3-surgeons was installed.

    Returns one of: "submodule", "standalone", "marketplace", "unknown".
    """
    git_path = plugin_root / ".git"
    if git_path.is_file():
        # .git is a file -> gitlink -> submodule
        return "submodule"
    if git_path.is_dir():
        return "standalone"
    # Check if inside a plugins directory (marketplace install)
    if "plugins" in str(plugin_root):
        return "marketplace"
    return "unknown"


@dataclass
class RegistrationResult:
    """Result of a symlink registration operation."""
    registered: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


class SkillRegistrar:
    """Discovers skills and manages symlinks for registration."""

    def __init__(self, plugin_root: Path) -> None:
        self._root = plugin_root
        self._skills_dir = plugin_root / "skills"

    def discover_skills(self) -> dict[str, Path]:
        """Find all skills with SKILL.md files.

        Returns dict of {skill_name: skill_dir_path}.
        """
        skills: dict[str, Path] = {}
        if not self._skills_dir.is_dir():
            return skills
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").exists():
                skills[entry.name] = entry
        return skills

    def create_symlinks(self, target_dir: Path) -> RegistrationResult:
        """Create symlinks from target_dir to each discovered skill.

        Args:
            target_dir: Directory where symlinks should be created
                        (e.g., ~/.claude/plugins/3-surgeons/skills/)

        Returns:
            RegistrationResult with counts.
        """
        result = RegistrationResult()
        skills = self.discover_skills()
        target_dir.mkdir(parents=True, exist_ok=True)

        for name, source_path in skills.items():
            link_path = target_dir / name
            if link_path.exists() or link_path.is_symlink():
                if link_path.is_symlink() and link_path.resolve() == source_path.resolve():
                    result.skipped += 1
                    continue
                # Remove stale symlink
                if link_path.is_symlink():
                    link_path.unlink()
            try:
                link_path.symlink_to(source_path)
                result.registered += 1
            except OSError as e:
                result.failed += 1
                result.errors.append(f"{name}: {e}")

        return result

    def check_symlink_health(self, target_dir: Path) -> List[str]:
        """Check for broken symlinks in target_dir.

        Returns list of broken symlink paths (as strings).
        """
        broken: List[str] = []
        if not target_dir.is_dir():
            return broken
        for entry in target_dir.iterdir():
            if entry.is_symlink() and not entry.resolve().exists():
                broken.append(str(entry))
        return broken

    def revert_symlinks(self, target_dir: Path) -> int:
        """Remove all symlinks from target_dir. Non-destructive.

        Returns count of removed symlinks.
        """
        removed = 0
        if not target_dir.is_dir():
            return removed
        for entry in target_dir.iterdir():
            if entry.is_symlink():
                entry.unlink()
                removed += 1
        return removed
