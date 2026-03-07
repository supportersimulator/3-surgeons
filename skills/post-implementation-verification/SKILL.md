---
name: post-implementation-verification
description: HARD-GATE — invoke before claiming any work is done or complete. Blocks completion claims until verification passes across all dimensions.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - TodoWrite
---

# Post-Implementation Verification

## Purpose

"It works on my machine" is not verification. This gate ensures that completed work is verified across infrastructure health, regression detection, and adversarial review before anyone claims "done."

<HARD-GATE>
Do NOT claim completion until this verification passes. "Done" means verified, not "I finished typing."
</HARD-GATE>

## Auto-Invocation Trigger

Invoke before ANY of these claims:
- "Done" / "complete" / "finished" / "implemented"
- "Ready for review" / "ready to merge"
- "All tests pass" (verify this claim, do not just assert it)
- "The fix is in" / "bug is resolved"
- Transitioning from executing-plans to completion

## Checklist

You MUST create a TodoWrite task for each step:

1. **Run gains-gate** — is infrastructure still healthy after changes? Changes can break things silently (port conflicts, stale locks, broken configs).

2. **Sentinel re-scan on actual changes** — scan the diff of what was actually implemented, not the original plan. Implementation often drifts from plan. The sentinel catches complexity introduced during implementation.

   ```bash
   # Get the diff for sentinel input
   git diff --stat HEAD~N  # or appropriate range
   git diff HEAD~N         # full diff for sentinel content
   ```

3. **If >3 files changed: quick consensus vote** — ask all 3 surgeons: "Did we introduce regression?" with the actual diff as context. This catches issues that tests miss.

4. **Verify tests pass** — run the actual test suite. Do not claim tests pass without running them. If no tests exist for the changed code, flag this as a gap.

5. **Counter-position: "What did we miss?"** — invoke counter-position with the claim "this implementation is complete and correct." Steelman why it is not.

6. **Present verification results** — summarize all findings. Only claim completion if all checks pass. If any check fails, fix the issue and re-run verification.

## Diff-Based Sentinel Scan

The post-implementation sentinel scan differs from pre-implementation:

- **Pre-implementation**: scans the plan/description (what you intend to do)
- **Post-implementation**: scans the actual diff (what you actually did)

This catches:
- Scope creep (changed more than planned)
- Unintended complexity (introduced patterns not in the plan)
- Security concerns in actual code (not just planned approach)

## Verification Levels

Scale verification to the size of change:

| Change Size | Verification |
|-------------|-------------|
| 1 file, clear scope | Gains-gate + sentinel re-scan |
| 2-5 files | Above + test verification |
| >5 files | Above + consensus vote + counter-position |

## Integration

```
[executing-plans] → [post-implementation-verification] → completion claim
```

This is the mirror of pre-implementation-review. Together they bracket the implementation phase:

```
pre-implementation-review → [implementation] → post-implementation-verification
```

## What NOT to Do

- **Do NOT skip verification because "it's a small change"** — small changes cause large outages. Light verification (gains-gate + sentinel) takes <30 seconds.
- **Do NOT claim "tests pass" without running them** — the verification is the running, not the claiming.
- **Do NOT dismiss sentinel warnings on the diff** — if sentinel flags something in what you actually wrote, investigate before dismissing.
