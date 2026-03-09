# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-05

### Added
- Multi-model consensus system with 3 LLM surgeons (Atlas/Claude, Cardiologist/API, Neurologist/Local)
- 21 skills: cross-examination, consensus, probe, sentinel, quality-gates, A/B testing, and more
- 7 commands: cross-exam, probe, sentinel, challenge, gains-gate, docs-init, surgeons
- MCP server with tool-based interface for IDE integration
- 5 config presets: hybrid, api-only, local-only, mlx-hybrid, generic-local
- Provider-agnostic design: any OpenAI-compatible endpoint
- SQLite state backend with zero external dependencies
- Evidence store with FTS5 full-text search
- Cost tracking with daily budget enforcement
- 20-vector complexity sentinel for risk assessment
- A/B testing framework with statistical validation
- Hook system: SessionStart, PreToolUse (Write/Edit gate), PostToolUse (Skill gate)
- Cross-platform support: Claude Code, Cursor, VS Code Agent Plugins
- Polyglot Windows/Unix hook runner
- ContextDNA adapter for priority queue integration
- CI/CD with GitHub Actions (Python 3.11/3.12, ruff lint, auto-releases)

### Security
- All API keys via environment variables only
- 6-step file access policy with denylist and prompt injection defense
- Comprehensive .gitignore for secrets, configs, databases
- yaml.safe_load() enforced throughout
- Parameterized SQL queries for all user-facing operations
