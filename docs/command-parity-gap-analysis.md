# 3-Surgeons Command Parity Gap Analysis

> **Date:** 2026-03-14
> **Goal:** 100% command parity across all 3 surfaces (CLI, MCP, HTTP) before declaring the plugin complete.
>
> **Updated 2026-03-14:** All 12 commands ported with capability-adaptive architecture (CLI + MCP + HTTP parity). Each command uses capability-adaptive gating (PROCEED/DEGRADED/BLOCKED based on detected infrastructure).

## Current State

| Surface | Commands | Coverage |
|---------|----------|----------|
| Standalone `scripts/surgery-team.py` | 25 commands | Reference implementation |
| Plugin CLI (`3s <cmd>`) | 31 commands | 100% (was 76%) |
| Plugin MCP (Claude Code tools) | 36 tools | Mapped from CLI |
| Plugin HTTP (`/tool/{name}`) | 36 endpoints | Mapped from CLI |

**All commands now have full plugin coverage across CLI, MCP, and HTTP.**

---

## Full Command Matrix

✅ = implemented | ❌ = missing | ➖ = N/A (plugin-only)

| # | Command | Standalone | Plugin CLI | MCP | HTTP | Dependencies |
|---|---------|:---:|:---:|:---:|:---:|---|
| 1 | probe | ✅ | ✅ | ✅ | ✅ | Local LLM |
| 2 | ask-local | ✅ | ✅ | ✅ | ✅ | Local LLM |
| 3 | ask-remote | ✅ | ✅ | ✅ | ✅ | OpenAI API |
| 4 | introspect | ✅ | ✅ | ✅ | ✅ | Local LLM |
| 5 | consult | ✅ | ✅ | ✅ | ✅ | Local LLM + OpenAI |
| 6 | cross-exam | ✅ | ✅ | ✅ | ✅ | Local LLM + OpenAI |
| 7 | consensus | ✅ | ✅ | ✅ | ✅ | Local LLM + OpenAI |
| 8 | research | ✅ | ✅ | ✅ | ✅ | OpenAI API |
| 9 | ab-propose | ✅ | ✅ | ✅ | ✅ | OpenAI API |
| 10 | ab-validate | ✅ | ✅ | ✅ | ✅ | Local LLM + OpenAI |
| 11 | cardio-review | ✅ | ✅ | ✅ | ✅ | OpenAI API |
| 12 | neurologist-pulse | ✅ | ✅ | ✅ | ✅ | Local LLM |
| 13 | neurologist-challenge | ✅ | ✅ | ✅ | ✅ | Local LLM |
| 14 | sentinel | ➖ | ✅ | ✅ | ✅ | None (static analysis) |
| 15 | gains-gate | ➖ | ✅ | ✅ | ✅ | Redis + health checks |
| 16 | setup-check | ➖ | ✅ | ✅ | ✅ | None |
| 17 | mode | ➖ | ✅ | ✅ | ✅ | Config file |
| 18 | docs-init | ➖ | ✅ | ✅ | ✅ | Filesystem |
| 19 | docs-scan | ➖ | ✅ | ✅ | ✅ | Filesystem |
| 20 | serve (HTTP) | ➖ | ✅ | ➖ | ➖ | HTTP server |
| 21 | migrate-evidence | ➖ | ✅ | ➖ | ➖ | Evidence store |
| 22 | status | ✅ | ✅ | ✅ | ✅ | Redis (telemetry) |
| 23 | research-status | ✅ | ✅ | ✅ | ✅ | Redis (cost tracking) |
| 24 | research-evidence | ✅ | ✅ | ✅ | ✅ | OpenAI API + evidence store |
| 25 | ab-start | ✅ | ✅ | ✅ | ✅ | Redis (state) |
| 26 | ab-measure | ✅ | ✅ | ✅ | ✅ | Local LLM + evidence store |
| 27 | ab-conclude | ✅ | ✅ | ✅ | ✅ | Redis + evidence store |
| 28 | ab-collaborate | ✅ | ✅ | ✅ | ✅ | Local LLM + OpenAI + Redis + evidence |
| 29 | ab-veto | ✅ | ✅ | ✅ | ✅ | `memory.ab_autonomous` module |
| 30 | ab-queue | ✅ | ✅ | ✅ | ✅ | `memory.ab_autonomous` module |
| 31 | cardio-reverify | ✅ | ✅ | ✅ | ✅ | OpenAI + Local LLM + Redis + git + evidence |
| 32 | deep-audit | ✅ | ✅ | ✅ | ✅ | OpenAI (3× chained) + Redis + evidence + git |

---

## Previously Missing Commands — Now Implemented (2026-03-14)

All 12 commands ported using capability-adaptive architecture. Each command detects available infrastructure (Redis, LLM, OpenAI, git, evidence store) and returns one of three gate states:
- **PROCEED** — all dependencies available, full functionality
- **DEGRADED** — partial dependencies, reduced functionality with clear indication of what's missing
- **BLOCKED** — critical dependencies unavailable, command cannot execute

### Tier: Display-Only (no API calls, read-only)

| Command | Lines | What It Does | Deps | Status |
|---------|-------|---|---|---|
| status | 64 | System health overview (LLM, Redis, costs, GPU lock) | Redis read | ✅ Implemented |
| research-status | 37 | Show research cost tracking & recent events | Redis read | ✅ Implemented |

### Tier: A/B Lifecycle (state management + optional LLM)

| Command | Lines | What It Does | Deps | Status |
|---------|-------|---|---|---|
| ab-start | 98 | Start an A/B test from a proposal | Redis state | ✅ Implemented |
| ab-measure | 84 | Measure running test with LLM assessment | Redis + Local LLM + evidence | ✅ Implemented |
| ab-conclude | 107 | Conclude test with verdict + learning | Redis + evidence store | ✅ Implemented |
| ab-veto | 18 | Veto an autonomous A/B test | `memory.ab_autonomous` | ✅ Implemented |
| ab-queue | 41 | Show autonomous A/B queue | `memory.ab_autonomous` | ✅ Implemented |

### Tier: Multi-Model Pipelines (chained API calls, heavy infra)

| Command | Lines | What It Does | Deps | Status |
|---------|-------|---|---|---|
| ab-collaborate | 323 | Full 3-surgeon A/B design session | OpenAI + Local LLM + Redis + evidence | ✅ Implemented |
| research-evidence | 246 | Evidence cross-check on research findings | OpenAI + evidence store + Redis | ✅ Implemented |
| cardio-reverify | 409 | Re-verify cardiologist findings against codebase | OpenAI + Local LLM + Redis + git + evidence | ✅ Implemented |
| deep-audit | 462 | 4-phase chained doc audit pipeline | OpenAI (3× calls) + Redis + evidence + git | ✅ Implemented |

---

## Completion Status

**All 32 commands** (rows 1-32 above) show ✅ across CLI, MCP, and HTTP columns.

Final: 31/31 CLI ✅, 36 MCP ✅, 36 HTTP ✅ (+ serve and migrate-evidence are CLI-only by design)

All 12 previously missing commands have been ported into the plugin's `core/` → `cli/` → `mcp/` → `http/` architecture with capability-adaptive gating.
