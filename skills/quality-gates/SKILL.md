---
name: quality-gates
description: Invoke between major phases (GainsGate), for quality reviews (CardioGate), or before risky actions (CorrigibilityGate) to enforce system health and safety invariants
---

# Quality Gates

## Three Gate Types

The 3-Surgeons system provides three quality gates, each serving a different purpose:

| Gate | Purpose | When to Run |
|------|---------|-------------|
| **GainsGate** | Infrastructure health verification | Between major phases, after deployments |
| **CardioGate** | Quality review chain with rate limiting | When quality degradation is detected |
| **CorrigibilityGate** | Safety invariant enforcement | Before destructive or risky actions |

## GainsGate

### When to Run

- **Between major phases** -- after completing phase A, run gains-gate before starting phase B
- **After deployments** -- verify the system is healthy post-deploy
- **After infrastructure changes** -- new config, restarted services, changed endpoints
- **Before long-running operations** -- ensure everything is healthy before committing to a multi-step process

### How to Invoke

#### CLI

```bash
3s gains-gate
```

#### MCP Tool

```
gains_gate()
```

### Default Checks

| Check | Critical? | What It Verifies |
|-------|-----------|-----------------|
| `neurologist_health` | No | Pings Neurologist endpoint. Local model may be offline. |
| `cardiologist_health` | No | Pings Cardiologist endpoint. API may be unavailable. |
| `evidence_store` | **Yes** | Evidence DB is accessible and queryable. |
| `state_backend` | **Yes** | State backend responds to ping. |

### Gate Pass/Fail Logic

The gate **passes** only if all **critical** checks pass. Non-critical failures are recorded but do not block progress.

- All critical checks pass + some non-critical fail = **PASS** (with warnings)
- Any critical check fails = **FAIL** (must fix before proceeding)

### Interpreting Results

```
Running gains gate...

  [PASS] neurologist_health: Neurologist operational (89ms)
  [FAIL] cardiologist_health: Cardiologist unreachable: Connection refused
  [PASS][critical] evidence_store: Evidence store accessible (42 learnings)
  [PASS][critical] state_backend: State backend operational

PASS: 3/4 checks passed (non-critical failures: cardiologist_health)  (23ms)
```

In this example, the gate **passes** because the Cardiologist being down is non-critical. The evidence store and state backend (both critical) are healthy.

### What to Do When the Gate Fails

1. **Read the failure messages** -- they tell you exactly which critical check failed and why
2. **Fix the root cause** -- do not proceed to the next phase with a failed gate
3. **Re-run the gate** -- verify the fix resolved the issue
4. **Only then proceed** -- the gate exists to prevent building on broken infrastructure

## CardioGate

### When to Run

- **When quality degradation is detected** -- automated monitoring flags declining output quality
- **For periodic quality reviews** -- scheduled quality assurance checks
- **After significant model or prompt changes** -- verify quality was not regressed

### How It Works

The CardioGate chains three steps:

1. **Rate limit check** (critical) -- maximum 3 automated reviews per hour. Prevents runaway quality checks from burning budget.
2. **Gains gate** (embedded) -- all GainsGate checks run as part of CardioGate. Infrastructure must be healthy before quality review.
3. **Optional cross-examination** -- if both previous steps pass, a cross-exam can be triggered for the quality concern.

### Rate Limiting

| Setting | Value |
|---------|-------|
| Max reviews per hour | 3 |
| State key | `cardio_gate:reviews_this_hour` |
| Tracked in | State backend |

If the rate limit is exceeded, the entire CardioGate fails with a critical `rate_limit` check failure. This prevents cost runaway from automated quality monitoring loops.

### Gate Failure

CardioGate fails if:
- Rate limit exceeded (critical)
- Any GainsGate critical check fails (critical)
- Both must pass for the gate to pass

## CorrigibilityGate

### When to Run

- **Before destructive operations** -- dropping tables, wiping data, force pushing
- **Before safety bypass requests** -- any action that would circumvent safety checks
- **Before modifying gate logic** -- self-modification of the safety system itself

### How to Invoke

The CorrigibilityGate is primarily used programmatically:

```python
from three_surgeons.core.gates import CorrigibilityGate
from three_surgeons.core.config import Config

gate = CorrigibilityGate(config=Config.discover())
result = gate.run(proposed_action="Drop all production database tables and recreate")
# result.passed = False
# result.summary = "CORRIGIBILITY FAIL: Blocked: No destructive operations without explicit approval (matched: 'Drop all...database tables')"
```

### Default Invariants

The gate checks proposed actions against these regex-based safety rules:

| Invariant | Catches |
|-----------|---------|
| **No destructive operations** | `drop database`, `truncate table`, `delete all prod data`, `rm -rf /`, `wipe all data`, `destroy database` |
| **No bypassing safety** | `bypass safety`, `skip safety`, `ignore safety`, `disable safety`, `override safety`, `circumvent safety`, `bypass constraint/check/validation/guard` |
| **No modifying gate logic** | `modify the gate logic`, `disable corrigibility gate`, `skip gains gate`, `remove cardio gate`, `bypass corrigibility gate` |
| **No force pushing** | `force push`, `push --force`, `git push -f` |

### Interpreting Results

```
CORRIGIBILITY PASS: action is safe (4 invariants checked)
```

or

```
CORRIGIBILITY FAIL: Blocked: No destructive operations without explicit approval (matched: 'drop all database tables')
```

A failed corrigibility check means the proposed action matches a safety invariant. The action should NOT proceed without explicit human approval.

### What to Do When CorrigibilityGate Fails

1. **Do NOT bypass the gate** -- the invariant exists for a reason
2. **Present the failure to the human** -- explain what was blocked and why
3. **Ask for explicit approval** -- if the human confirms the action is intentional, they can authorize proceeding
4. **The gate itself cannot be modified** -- "disable corrigibility gate" is itself an invariant violation

## Decision Table: Which Gate?

| Situation | Gate |
|-----------|------|
| Transitioning between project phases | GainsGate |
| After deploying changes | GainsGate |
| Quality metric declining | CardioGate |
| About to delete/drop/wipe something | CorrigibilityGate |
| About to force push | CorrigibilityGate |
| Session start health check | GainsGate (or just probe for quick check) |
| About to modify safety settings | CorrigibilityGate |

## Gate Composition

Gates can be composed. The CardioGate already embeds a GainsGate. You could build custom workflows:

```
CorrigibilityGate -> GainsGate -> (proceed with operation)
```

This pattern ensures: (1) the action is safe, (2) the infrastructure is healthy, (3) then execute.
