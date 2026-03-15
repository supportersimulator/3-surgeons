---
name: ab-validate
description: Rapid 3-surgeon verdict on whether a proposed fix or change is sound
---

# A/B Validate

Quick 3-surgeon validation for proposed fixes. Faster than full cross-examination, more rigorous than a single opinion.

## When to Use

- After writing a bug fix, before committing
- After a refactor, to sanity-check the approach
- When you want a quick thumbs-up/thumbs-down from all three surgeons
- For validating that a proposed change doesn't introduce regressions

## When NOT to Use

- Major architectural decisions → use `cross-examination` instead
- Comparing two approaches → use `ab-testing` instead
- Just need one surgeon's opinion → use `direct-query` instead

## How It Works

1. Describe the fix or change
2. All three surgeons vote independently
3. Results synthesized into a verdict

## Output

- `verdict` — approved, rejected, or needs-review
- `reasoning` — why the verdict was reached
- `surgeon_votes` — each surgeon's individual vote (disagreements visible)

**MCP tool:** `ab_validate_tool`
**CLI:** `3s ab-validate "description of the fix"`

## Cost

~$0.001-0.003 per validation.
