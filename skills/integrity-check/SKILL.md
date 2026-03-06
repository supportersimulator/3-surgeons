---
name: integrity-check
description: Use for structural integrity verification — checks monotonic counters, service health, and evidence store operability to detect tampering or state corruption
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

Without a state backend, integrity checks are skipped (passes with "skipped" message).

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
