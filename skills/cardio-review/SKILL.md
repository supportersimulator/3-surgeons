---
name: cardio-review
description: Use for cardiologist cross-examination reviews with optional git context — the external perspective on code changes, architecture decisions, and potential blind spots
---

# Cardio Review

The Cardiologist (GPT-4.1-mini) provides cross-examination reviews that combine external analysis with neurologist blind-spot detection.

## When to Use

- After implementing a significant change (>3 files touched)
- Before merging a feature branch
- When you want an external perspective on an architectural decision
- When git context would help (pass recent changes for targeted review)

## How It Works

1. Cardiologist analyzes the topic independently
2. Neurologist identifies blind spots the cardiologist might miss
3. Results are synthesized with any dissent preserved
4. Recommendations generated

## With Git Context

Pass `--git-context` to include recent changes:

```bash
3s cardio-review "authentication refactor" --git-context "$(git diff HEAD~3)"
```

The cardiologist will analyze the actual code changes alongside the topic.

## Output

- `cardiologist_findings` — external analysis
- `neurologist_blind_spots` — what the cardiologist might have missed
- `synthesis` — combined view
- `dissent` — any unresolved disagreements (preserved, not hidden)
- `recommendations` — actionable next steps

**MCP tool:** `cardio_review_tool`
**CLI:** `3s cardio-review "topic" [--git-context "changes"]`

## Cost

~$0.002-0.005 per review (cardiologist API call + neurologist is free).
