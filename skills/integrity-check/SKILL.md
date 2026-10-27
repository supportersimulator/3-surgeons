---
name: integrity-check
description: Structural integrity verification — monotonic counters, service health, and evidence store operability
---

# Integrity Check

The CorrigibilityGate's integrity verification mode. Detects state corruption, counter tampering, and service degradation.

## When to Use

- After a crash or unexpected restart
- When state values seem inconsistent
- After manual state modifications
- Periodic health verification (beyond what gains-gate checks)

## What It Checks

- **Monotonic counters** — event counts should only increase. A decrease signals data loss or tampering.
- **Service health** — state backend is responding to pings.
- **Evidence operational** — evidence store can be queried.

## How It Works

The integrity check reads `integrity:*` keys from the state backend:
- `integrity:events_count` vs `integrity:events_count:prev`
- If current < previous → something decreased a counter → FAIL

The check is **fail-closed**: a PASS is only issued when integrity is demonstrated.
- Required: a state backend, and `integrity:events_count`, `integrity:learnings_count`,
  `integrity:evidence_grade_sum` present as integers. Missing or malformed -> FAIL.
- Optional: each counter's `:prev` baseline (absent on first observation -> no comparison),
  and the evidence-store check (only when an EvidenceStore is supplied).

Every failing check names the condition and a `Recovery:` step; failures are logged at ERROR.

## Output

Standard `GateResult`:
- `passed` — true if all checks pass
- `checks` — individual check results with names and messages
- `duration_ms` — how long the check took

## Relationship to Other Gates

| Gate | Purpose | When |
|------|---------|------|
| **GainsGate** | Infrastructure health | Between phases |
| **CardioGate** | Quality review + rate limit | Automated quality checks |
| **CorrigibilityGate.run()** | Text safety (regex) | Before destructive ops |
| **CorrigibilityGate.check_integrity()** | Structural integrity | After crashes, periodic |
