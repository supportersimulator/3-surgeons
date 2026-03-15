---
name: direct-query
description: Direct answer from a specific surgeon without consensus overhead
---

# Direct Query

Bypass the consensus protocol for targeted surgeon access. Use when you need a specific model's perspective, not a synthesis.

## When to Use Direct vs Consensus

| Situation | Use |
|-----------|-----|
| Quick classification or pattern match | `ask-local` (free, fast) |
| Need external perspective with evidence | `ask-remote` (~$0.0005) |
| Two surgeons disagree on something | `test-dissent` (steelmans minority) |
| Critical decision needs all three views | Cross-examination (not this skill) |

## ask-local (Neurologist)

Direct query to the local Qwen3-4B. Zero cost, fast, good for pattern recognition and classification.

**Best for:** keyword extraction, severity classification, pattern matching, quick sanity checks.

**MCP tool:** `ask_local_tool`
**CLI:** `3s ask-local "your prompt"`

## ask-remote (Cardiologist)

Direct query to GPT-4.1-mini. Costs ~$0.0002-0.001 per query. Stronger reasoning, broader knowledge.

**Best for:** nuanced analysis, evidence evaluation, design review, research questions.

**MCP tool:** `ask_remote_tool`
**CLI:** `3s ask-remote "your prompt"`

## Dissent Testing

When surgeons disagree, the dissent protocol steelmans the minority position before dismissing it.

**Process:**
1. Identify the disagreement topic and the minority view
2. `test_dissent` asks a surgeon to build the strongest possible case FOR the minority view
3. Returns: steelmanned argument, counter-evidence, verdict (valid/partially valid/unfounded), confidence

**Verdicts:**
- `dissent_valid` — minority was right, reconsider the majority position
- `dissent_partially_valid` — minority has a point, investigate further
- `dissent_unfounded` — majority position holds after steelmanning

**Use `resolve_disagreement`** when you have a dict of surgeon opinions and want automated dissent resolution.

**Philosophy:** *"An opinion is not valid until you can argue both sides."*
