---
name: pre-implementation-review
description: HARD-GATE — adversarial review of implementation plans by all 3 surgeons before coding begins
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - TodoWrite
---

# Pre-Implementation Review

## Purpose

The gap between "good plan" and "good implementation" is where most bugs are born. This gate ensures the plan survives adversarial scrutiny BEFORE any code is written.

<HARD-GATE>
Do NOT start implementation until this review passes. This fires at the writing-plans to executing-plans transition.
</HARD-GATE>

## Auto-Invocation Trigger

Invoke when transitioning from planning to implementation — specifically:
- After `writing-plans` skill produces an implementation plan
- Before `executing-plans` skill begins work
- Before any multi-file implementation begins
- When a design doc exists and coding is about to start

## Checklist

You MUST create a TodoWrite task for each step:

1. **Sentinel scan on the implementation plan** — run sentinel with the plan description as content. This catches complexity risks the planning phase may have introduced.

2. **Cross-exam the plan with all 3 surgeons** — focus question: "What will break when we implement this?" Not "is this a good idea?" (that was architectural-gate's job) but "what will go wrong during execution?"

3. **Counter-position: argue why this plan will FAIL** — invoke the counter-position skill. The claim is "this implementation plan will succeed." Steelman why it will not.

4. **Verify gains-gate passes** — infrastructure must be healthy before starting. Do not build on broken foundations.

5. **Create explicit rollback strategy** — before writing code, document how to undo the changes if they go wrong. This forces thinking about reversibility.

6. **Present review results** — summarize findings from steps 1-5. Proceed only with approval. If surgeons raised critical concerns, those must be addressed in the plan before implementation begins.

## What the Cross-Exam Should Focus On

The cross-exam question for pre-implementation is specifically:

```
We are about to implement the following plan:
[plan summary]

Focus your analysis on:
1. What will break during implementation?
2. What dependencies or ordering constraints are missing?
3. What edge cases does the plan not address?
4. Are there simpler approaches the plan overlooked?
5. What tests should exist BEFORE implementation starts?
```

This is different from architectural-gate's cross-exam (which focuses on "is this the right approach?"). Pre-implementation focuses on "will this execution succeed?"

## Rollback Strategy Template

Every pre-implementation review must produce a rollback strategy:

```
## Rollback Strategy
- Files that will change: [list]
- Git state before: [commit hash or branch]
- Rollback command: git checkout [hash] -- [files]
- Data migrations: [reversible? how?]
- External state: [any API keys, configs, or services that change?]
- Estimated rollback time: [minutes]
```

If the rollback strategy reveals the change is hard to reverse, this is a signal to increase scrutiny (potentially escalating to Full mode in architectural-gate if not already there).

## Integration

```
[architectural-gate] → [brainstorming] → [writing-plans] → [pre-implementation-review] → [executing-plans]
```

Pre-implementation-review is the last checkpoint before code changes begin. After this, the next gate is post-implementation-verification.
