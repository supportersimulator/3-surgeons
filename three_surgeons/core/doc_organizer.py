"""4-Folder Document System setup and project detection.

Creates inbox/vision/reflect/dao folders with README files and .gitignore entries.
Detects monorepo/superrepo structure to recommend per-project folders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


FOLDERS = ["inbox", "vision", "reflect", "dao"]

FOLDER_DESCRIPTIONS = {
    "inbox": (
        "# Inbox (L1 Soft Tissue)\n\n"
        "Raw ideas, chat exports, research notes, brainstorming transcripts.\n\n"
        "**Trust:** LOW\n"
        "**Rules:** Append-only. Never deleted. Validity notations added over time\n"
        "to mark what's been absorbed into vision specs.\n\n"
        "Dump anything here. It stays forever."
    ),
    "vision": (
        "# Vision (L2 Markdown Truth)\n\n"
        "Specs, designs, architecture decisions, feature proposals.\n\n"
        "**Trust:** MEDIUM\n"
        "**Rules:** Written through collaboration -- brainstorming sessions,\n"
        "3-surgeon cross-examinations, human decisions. Evolves as understanding deepens.\n\n"
        "This is what we want to build."
    ),
    "reflect": (
        "# Reflect (L3 Code Reality)\n\n"
        "What the code actually does today. Written FROM code, not from specs.\n\n"
        "**Trust:** HIGH\n"
        "**Rules:** Updated when implementation changes. Shows where shortcuts were taken,\n"
        "where complexity accumulated, where implementation diverged from vision.\n\n"
        "This is a mirror, not an aspiration."
    ),
    "dao": (
        "# Dao (L4 Aspirational Alignment)\n\n"
        "Patterns validated through evidence and experience.\n\n"
        "**Trust:** HIGHEST\n"
        "**Rules:** Changes only with empirical proof. Contains patterns that proved\n"
        "themselves across multiple contexts. Not a destination but a practice of returning.\n\n"
        "The gap between reflect and dao is the work."
    ),
}

GITIGNORE_BLOCK = """
# 4-Folder Document System (inbox/vision/reflect/dao)
docs/inbox/
docs/vision/
docs/reflect/
docs/dao/
"""


@dataclass
class DetectedProject:
    """A project detected within a repo that may deserve its own 4 folders."""

    path: Path
    name: str
    reason: str
    has_readme: bool = False
    has_package_manifest: bool = False
    has_tests: bool = False
    is_submodule: bool = False

    @property
    def score(self) -> int:
        """Number of independence signals (2+ = recommend own folders)."""
        return sum([
            self.has_readme,
            self.has_package_manifest,
            self.has_tests,
            self.is_submodule,
        ])

    @property
    def recommended(self) -> bool:
        return self.score >= 2


@dataclass
class ScanResult:
    """Result of scanning a repo for project structure."""

    root: Path
    projects: List[DetectedProject] = field(default_factory=list)
    is_superrepo: bool = False


@dataclass
class InitResult:
    """Result of initializing 4-folder system in a directory."""

    path: Path
    folders_created: List[str] = field(default_factory=list)
    gitignore_updated: bool = False
    already_existed: List[str] = field(default_factory=list)


def init_docs(target: Path, update_gitignore: bool = True) -> InitResult:
    """Create the 4-folder document system in target/docs/.

    Creates docs/inbox/, docs/vision/, docs/reflect/, docs/dao/ with README.md
    files explaining each folder's purpose. Optionally updates .gitignore.
    """
    result = InitResult(path=target)
    docs_dir = target / "docs"

    for folder_name in FOLDERS:
        folder_path = docs_dir / folder_name
        readme_path = folder_path / "README.md"

        if folder_path.exists():
            result.already_existed.append(folder_name)
            # Still write README if missing
            if not readme_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
                readme_path.write_text(FOLDER_DESCRIPTIONS[folder_name] + "\n")
                result.folders_created.append(folder_name)
        else:
            folder_path.mkdir(parents=True, exist_ok=True)
            readme_path.write_text(FOLDER_DESCRIPTIONS[folder_name] + "\n")
            result.folders_created.append(folder_name)

    if update_gitignore:
        result.gitignore_updated = _update_gitignore(target)

    return result


def scan_repo(root: Path) -> ScanResult:
    """Scan a repository for distinct projects that deserve their own 4 folders.

    Checks for:
    - .gitmodules (submodules)
    - Common monorepo patterns (packages/, apps/, services/, libs/)
    - Independent package manifests in subdirectories
    - Independent READMEs in subdirectories
    """
    result = ScanResult(root=root)

    # Check for submodules
    gitmodules = root / ".gitmodules"
    submodule_paths: set[str] = set()
    if gitmodules.exists():
        result.is_superrepo = True
        for line in gitmodules.read_text().splitlines():
            line = line.strip()
            if line.startswith("path = "):
                submodule_paths.add(line.split("=", 1)[1].strip())

    for sm_path in sorted(submodule_paths):
        full_path = root / sm_path
        if full_path.is_dir():
            project = _evaluate_directory(full_path, sm_path)
            project.is_submodule = True
            result.projects.append(project)

    # Check common monorepo directories
    monorepo_parents = ["packages", "apps", "services", "libs", "modules"]
    for parent_name in monorepo_parents:
        parent_dir = root / parent_name
        if parent_dir.is_dir():
            for child in sorted(parent_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    rel = str(child.relative_to(root))
                    if rel not in submodule_paths:
                        project = _evaluate_directory(child, rel)
                        if project.score >= 1:
                            result.projects.append(project)

    # Check top-level directories that look like independent projects
    # (have their own package manifest + README)
    manifests = {
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "Gemfile",
    }
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        rel = str(child.relative_to(root))
        if rel in submodule_paths:
            continue
        if rel in monorepo_parents:
            continue
        # Skip common non-project dirs
        if rel in {"node_modules", "vendor", "dist", "build", "docs", ".git",
                    "scripts", "config", "tests", "test", "__pycache__"}:
            continue
        has_manifest = any((child / m).exists() for m in manifests)
        has_readme = (child / "README.md").exists() or (child / "readme.md").exists()
        if has_manifest and has_readme:
            project = _evaluate_directory(child, rel)
            if project.score >= 2:
                result.projects.append(project)

    return result


def _evaluate_directory(path: Path, rel_path: str) -> DetectedProject:
    """Evaluate a directory for independence signals."""
    manifests = {
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "Gemfile",
    }
    has_readme = (path / "README.md").exists() or (path / "readme.md").exists()
    has_manifest = any((path / m).exists() for m in manifests)
    has_tests = (
        (path / "tests").is_dir()
        or (path / "test").is_dir()
        or (path / "__tests__").is_dir()
    )

    reasons = []
    if has_readme:
        reasons.append("has README")
    if has_manifest:
        reasons.append("has package manifest")
    if has_tests:
        reasons.append("has tests")

    return DetectedProject(
        path=path,
        name=path.name,
        reason=", ".join(reasons) if reasons else "subdirectory",
        has_readme=has_readme,
        has_package_manifest=has_manifest,
        has_tests=has_tests,
    )


def _update_gitignore(target: Path) -> bool:
    """Add 4-folder entries to .gitignore if not already present."""
    gitignore_path = target / ".gitignore"

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "docs/inbox/" in content:
            return False  # Already has entries
        # Append
        if not content.endswith("\n"):
            content += "\n"
        content += GITIGNORE_BLOCK
        gitignore_path.write_text(content)
    else:
        gitignore_path.write_text(GITIGNORE_BLOCK.lstrip())

    return True
