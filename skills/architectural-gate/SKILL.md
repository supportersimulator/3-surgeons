---
name: architectural-gate
description: HARD-GATE — invoke before ANY architectural decision, new subsystem, >3 file changes, security/schema/API/dependency/infra changes. Blocks implementation until gate passes.
allowed-tools:
  - Bash
  - TodoWrite
  - Agent
  - Read
  - Grep
  - Glob
---

# Architectural Gate

## The Core Invariance Skill

This is the primary quality gate for the 3-Surgeons invariance suite. It ensures that no significant change proceeds without proportional scrutiny.

<HARD-GATE>
Do NOT implement changes until this gate passes. The gate can be quick (Light mode) or thorough (Full mode), but it MUST run. Skipping this gate violates epistemological invariance.
</HARD-GATE>

## Auto-Invocation Triggers

Invoke this skill when ANY of these signals are present:

| Signal | Examples |
|--------|----------|
| Architectural decision | New subsystem, data flow change, module restructuring |
| >3 files will change | Multi-file refactor, cross-cutting concern |
| New dependency added | npm/pip package, external service, API integration |
| Security-sensitive code | Auth, crypto, input validation, secrets handling |
| Database schema change | Migration, new table, index change, column alter |
| API surface change | New endpoint, modified contract, breaking change |
| Config/infrastructure change | Docker, CI/CD, env vars, deploy config |

**If even ONE signal is present, this gate fires.**

## Risk Stratification

Not all changes need full gating. The gate assesses risk across multiple dimensions and selects a proportional mode:

### Risk Dimensions (multi-axis, not scalar)

| Dimension | Low | Medium | High |
|-----------|-----|--------|------|
| **Blast radius** | 1 file | 2-5 files | >5 files |
| **Reversibility** | Easy rollback | Moderate effort | Hard/impossible |
| **Security exposure** | No auth/crypto | Touches validation | Auth/crypto/secrets |
| **Data impact** | Read-only | Schema additive | Schema destructive |
| **External coupling** | No new deps | New internal dep | New external service |

### Mode Selection

| Mode | When | What Runs | Target Time |
|------|------|-----------|-------------|
| **Light** | All dimensions Low. Single-file, clear scope, no arch change | Sentinel scan only. If risk=low, proceed. | <30s |
| **Standard** | Any dimension Medium. 2-5 files, moderate complexity | Sentinel + gains-gate. Cross-exam if sentinel >= medium. | <120s |
| **Full** | Any dimension High. >5 files, security, schema, new subsystem | Sentinel + cross-exam + counter-position + gains-gate. | <300s |

**Mode is determined by highest-risk dimension, not average.** One High dimension = Full mode, even if everything else is Low.

## Checklist

You MUST create a TodoWrite task for each step and complete them in order:

### Light Mode
1. Run `sentinel` scan on planned change description
2. If sentinel risk = none or low: **GATE PASSES** — proceed
3. If sentinel risk >= medium: escalate to Standard mode

### Standard Mode
1. Run `sentinel` scan on planned change description
2. Run `gains-gate` to verify infra health before implementation
3. If sentinel risk >= medium: run `cross-examination` on the plan
4. Present gate results — proceed only if no critical flags
5. After implementation: run `gains-gate` again (post-gate)

### Full Mode
1. Run `sentinel` scan on planned change description
2. Run `cross-examination` on the plan (all 3 surgeons)
3. Run `counter-position` protocol — argue why this plan will FAIL
4. Run `gains-gate` to verify infra health
5. Present gate results with all surgeon opinions — proceed only with approval
6. After implementation: run `gains-gate` again (post-gate)
7. If post-gate fails: diagnose and fix before claiming done

## Emergency Bypass Protocol

For critical hotfixes (production down, security vulnerability, data loss):

1. **Declare emergency** — state what is broken and why bypass is needed
2. **Implement fix** — proceed without full gating
3. **Post-mortem gate** — within 24h, run Full mode architectural-gate on the emergency fix
4. **Evidence capture** — log bypass reason, outcome, and whether the gate would have caught the issue
5. **Surface to Aaron** — emergency bypasses always surface to the human operator

This is the release valve. It exists so the gate does not become the thing that kills the system it protects.

## Integration with Superpowers

This skill fires BEFORE brainstorming/writing-plans. It supplements the superpowers workflow:

```
Signal detected → architectural-gate → [brainstorming] → [writing-plans] → [executing-plans]
```

The gate does NOT replace superpowers' process invariance. It adds epistemological invariance on top — ensuring the right questions are asked before the process begins.

## What NOT to Do

- **Do NOT skip the gate because it "seems simple"** — Light mode exists for simple changes. Use it.
- **Do NOT run Full mode on everything** — that creates cross-exam fatigue and delivery freeze.
- **Do NOT ignore sentinel warnings** — if sentinel flags medium+, escalate. The flag is the value.
- **Do NOT override surgeon disagreements without evidence** — present disagreements to Aaron.
