---
name: review-loop
description: Selects review depth mode for 3-surgeon cross-exam based on task risk
trigger: automatic
type: HARD-GATE
---

# Review Loop Mode Selector

## Purpose

Before any 3-surgeon cross-exam, determine the appropriate review depth mode based on task risk signals.

## Modes

| Mode | Iterations | When |
|------|-----------|------|
| **single** | 1 | Config changes, docs, small fixes, <=2 files |
| **iterative** | up to 3 | Multi-file changes, new features, refactors, 3-10 files |
| **continuous** | up to 5 | Security, schema, API, architecture, >10 files |

## Risk Assessment

Evaluate these dimensions. **Highest-risk dimension wins:**

| Dimension | single | iterative | continuous |
|-----------|--------|-----------|------------|
| Files changed | 1-2 | 3-10 | >10 |
| Reversibility | Fully | Partially | Hard to reverse |
| Security | None | Internal | External/auth |
| Data impact | Read-only | Schema-preserving | Schema-changing |
| External coupling | None | Internal APIs | Public APIs |

## Project-Level Awareness

Some projects warrant deeper review by default. Check:
- `.3surgeons/config.yaml` in project root for `review.depth`
- Accumulated review outcome weights via `3s review-weights show`
- Project complexity signals: cross-file deps, security code, submodules

For sustained development on complex projects (e.g., ContextDNA), continuous mode is the natural default.

## Intent Mapping (Conversational)

| User says | Maps to |
|-----------|---------|
| "quick review", "just a glance" | single |
| "thorough review", "check carefully" | iterative |
| "loop until satisfied", "full depth", "keep going" | continuous |
| "3-surgeons full" | continuous |

## Auto-Depth Behavior

Based on `auto_review_depth` config:
- **off**: Always use config default or CLI flag
- **suggest**: Recommend mode with reasoning, wait for confirmation
- **auto**: Apply learned weights, user can override anytime

## Exit Conditions

- **Consensus >= 0.7** on "all issues addressed" → exit loop
- **Max iterations reached** without consensus → escalate to human with unresolved summary
- **User override** at any point → respect immediately

## After Review

Record outcome to evidence store for adaptive learning:
- Mode used, iterations, consensus score, files changed, user override (if any)
