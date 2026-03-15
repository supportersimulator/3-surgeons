---
name: doc-organizer
description: Set up the 4-folder document system (inbox/vision/reflect/dao) in a project
---

# Doc Organizer -- 4-Folder Document System

## What This Does

Sets up a 4-folder document system that separates ideas from specs from code reality from proven patterns. Each folder has a different trust level. Documents don't move between folders -- each generates independently.

## The Four Folders

| Folder | What Goes Here | Trust | Who Writes It |
|--------|---------------|-------|---------------|
| `docs/inbox/` | Raw ideas, chat exports, research notes | LOW | Anyone. Append-only. Never deleted. |
| `docs/vision/` | Specs, designs, architecture decisions | MEDIUM | Human + AI collaboration (brainstorming, cross-exam) |
| `docs/reflect/` | What the code actually does today | HIGH | Written FROM code analysis, not from specs |
| `docs/dao/` | Patterns validated through evidence | HIGHEST | Emerges from outcomes, changes only with proof |

## When to Invoke This Skill

- **Project setup** -- user runs `3s docs-init` or asks about document organization
- **Onboarding** -- new team member or AI agent needs to understand the knowledge structure
- **Drift detected** -- documents are accumulating without structure, or specs diverge from reality

## Setup Process

### Step 1: Detect Project Structure

Before creating folders, evaluate the project:

1. **Single repo?** -- Create one set of 4 folders at `docs/`
2. **Monorepo with distinct projects?** -- Each project that has its own domain, its own codebase concerns, and its own decision history deserves its own 4 folders
3. **Superrepo with submodules?** -- Each submodule gets its own 4 folders. The superrepo gets cross-cutting 4 folders for ecosystem-level docs.

**How to decide if a subdirectory deserves its own 4 folders:**
- Does it have its own README or documentation?
- Does it make architectural decisions independently?
- Could someone work on it without understanding the rest of the repo?
- Does it have (or should it have) its own tests?

If yes to 2+ of these, it deserves its own 4 folders.

### Step 2: Create Folders

For each project/submodule identified:

```bash
3s docs-init                    # Current directory
3s docs-init path/to/subproject # Specific path
3s docs-init --scan             # Auto-detect projects in repo
```

This creates:
```
docs/inbox/README.md
docs/vision/README.md
docs/reflect/README.md
docs/dao/README.md
```

Each README explains the folder's purpose so anyone opening the folder understands what belongs there.

### Step 3: Configure .gitignore

The 4 folders are gitignored by default -- they contain local working documents, not committed artifacts. The `3s docs-init` command adds these entries:

```gitignore
# 4-Folder Document System (inbox/vision/reflect/dao)
docs/inbox/
docs/vision/
docs/reflect/
docs/dao/
```

**Why gitignored?** These are working documents for the human + AI collaboration loop. They evolve constantly, contain large chat exports, and are personal to the development workflow. The code itself (committed) is the source of truth -- these folders support the thinking process.

**Exception:** If the team decides certain vision docs should be shared (e.g., architecture decisions that affect multiple contributors), they can force-add specific files: `git add -f docs/vision/architecture.md`.

### Step 4: Explain to the User

After setup, explain the system conversationally:

> **Your project now has 4 knowledge folders.** Think of them as layers of trust:
>
> - **inbox/** is your scratchpad -- dump ideas, paste conversations, save research. Nothing gets deleted, but over time we'll mark what's been absorbed into proper specs.
>
> - **vision/** is where decisions live -- when we brainstorm a feature or the surgeons cross-examine an approach, the result goes here as a spec.
>
> - **reflect/** is the honest mirror -- written from the code itself, showing what you actually built (not what you planned to build). The gap between vision and reflect is where the interesting work lives.
>
> - **dao/** is for patterns that proved themselves -- things that worked across multiple projects or survived multiple sessions of evidence. These change slowly and only with proof.
>
> Documents don't move between folders. Each one generates its own content independently.

## Monorepo/Superrepo Detection

When `--scan` is used, evaluate the repo structure:

1. Check for `.gitmodules` (submodules) -- each submodule is a candidate
2. Check for common monorepo patterns: `packages/`, `apps/`, `services/`, `libs/`
3. Check for independent `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod` in subdirectories
4. Check for independent README files in subdirectories
5. Present findings to the user:

```
Detected project structure:

  [repo root] -- superrepo (cross-cutting docs)
  packages/api/ -- independent project (has own pyproject.toml, README, tests)
  packages/web/ -- independent project (has own package.json, README)
  packages/shared/ -- shared library (skip -- no independent decisions)

Recommendation: Create 4-folder system in repo root + packages/api/ + packages/web/
Skip packages/shared/ (shared utility, decisions made in consuming projects)

Proceed? [Y/n]
```

## Validity Notations (Inbox Lifecycle)

Inbox documents never get deleted, but they do get annotated over time. When content from an inbox doc gets absorbed into a vision spec, add a validity notation:

```markdown
> **VALIDITY NOTATION** (YYYY-MM-DD):
> - Status: ABSORBED | PARTIALLY ABSORBED | OPEN | INVALIDATED
> - Promoted to: `docs/vision/spec-name.md`
> - Key decisions preserved: [list]
> - Remaining value: original phrasing for intent archaeology
```

This creates a paper trail: anyone can trace a vision spec back to the raw conversation that spawned it.

## Integration with 3-Surgeons

The 4-folder system works naturally with the 3-surgeon protocol:

- **Cross-examination results** go to `docs/vision/` as decision records
- **Neurologist challenges** that prove valid update `docs/reflect/` (code reality corrections)
- **Evidence from A/B tests** feeds `docs/dao/` when patterns validate
- **Sentinel scans** may flag drift between vision and reflect
