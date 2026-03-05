---
name: sentinel
description: Invoke before major changes, after feature completion, or for periodic scans to detect complexity risks across configurable dimensions
---

# Sentinel

## When to Run

The Sentinel scans content for complexity indicators across multiple dimensions (vectors). It answers the question: "What risks am I not seeing?" Run it:

- **Before major changes** -- scan the diff or plan description to surface hidden risks
- **After feature completion** -- scan the implementation to catch complexity you introduced
- **Periodic scans** -- scan key files or modules to monitor complexity drift over time
- **Before cross-examination** -- if sentinel flags high risk, escalate to full cross-exam

**Do NOT use for**: health checks (use probe), claim validation (use consensus), or infrastructure verification (use gains-gate).

## How to Invoke

### CLI

```bash
3s sentinel "Refactoring the authentication module to use JWT tokens with Redis-backed session storage and a new OAuth2 provider integration"
```

### MCP Tool

```
sentinel_run(content="Refactoring the authentication module to use JWT tokens with Redis-backed session storage and a new OAuth2 provider integration")
```

The `content` parameter is the text to scan -- it can be a description of planned work, a code diff, a commit message, or any text that describes what you are doing.

## How It Works

### Complexity Vectors

The Sentinel evaluates content against a set of complexity vectors. Each vector has:

| Property | Purpose |
|----------|---------|
| **keywords** | Terms to search for in the content (case-insensitive) |
| **risk_score** | Severity weight from 0.0 to 1.0 |
| **noise_threshold** | Maximum keyword hits before the vector is discarded as noise |

### Default Vectors

| ID | Vector | Keywords | Risk Score |
|----|--------|----------|------------|
| CV-001 | Authentication complexity | auth, token, jwt, oauth, session | 0.7 |
| CV-002 | Database schema changes | migration, schema, alter table, index | 0.6 |
| CV-003 | API surface changes | endpoint, route, api, rest, graphql | 0.5 |
| CV-004 | Security concerns | injection, xss, csrf, vulnerability, exploit | 0.9 |
| CV-005 | Performance impact | cache, latency, throughput, bottleneck, n+1 | 0.6 |
| CV-006 | Concurrency issues | lock, mutex, race condition, deadlock, thread | 0.8 |
| CV-007 | External dependencies | api key, third-party, vendor, sdk, external | 0.5 |
| CV-008 | State management | state, redux, context, global, singleton | 0.4 |

### The Noise Gate

If a keyword appears more than `noise_threshold` times (default 6) in the content, that vector is **discarded** rather than triggered. Why? Content that mentions "auth" 20 times is probably an authentication module -- the keyword is ubiquitous in that context and not a useful risk signal. The noise gate prevents false positives from domain-specific content.

A vector triggers only when: `0 < hits <= noise_threshold`.

### Scoring

The overall score is the average of all triggered vectors' risk scores:

```
overall_score = sum(triggered_risk_scores) / count(triggered_vectors)
```

If no vectors trigger, the score is 0.0.

## Interpreting Risk Levels

| Risk Level | Score Range | Meaning | Recommended Action |
|------------|-------------|---------|-------------------|
| **none** | 0.0 | No complexity vectors triggered | Proceed normally |
| **low** | 0.01 - 0.19 | Minor complexity detected | Monitor, no special action |
| **medium** | 0.20 - 0.49 | Moderate complexity | Review before proceeding |
| **high** | 0.50 - 0.79 | Significant complexity | Consider cross-examination before proceeding |
| **critical** | 0.80 - 1.0 | Multiple high-risk vectors triggered | Cross-examination strongly recommended |

## Reading the Output

### CLI Output

```
Sentinel scan: 8 vectors checked
Triggered: 3 | Risk: high | Score: 0.67

Triggered vectors:
  [CV-001] Authentication complexity -- 3 hits (risk=0.7)
  [CV-006] Concurrency issues -- 2 hits (risk=0.8)
  [CV-005] Performance impact -- 1 hits (risk=0.6)

Recommendations:
  - High concurrency issues detected -- consider cross-examination
  - Elevated authentication complexity -- review before proceeding
  - Elevated performance impact -- review before proceeding
```

### Key Fields

| Field | What It Tells You |
|-------|-------------------|
| `vectors_checked` | Total vectors evaluated (usually 8 with defaults) |
| `vectors_triggered` | How many had keyword hits within noise threshold |
| `risk_level` | Aggregate risk category (none/low/medium/high/critical) |
| `overall_score` | Numeric risk score 0.0-1.0 |
| `triggered_vectors` | Details: which vectors, how many hits, individual risk scores |
| `recommendations` | Actionable suggestions per triggered vector |

## Recommendations Logic

The Sentinel generates one recommendation per triggered vector:

| Vector Risk Score | Recommendation Template |
|-------------------|------------------------|
| >= 0.8 | "High {vector name} detected -- consider cross-examination" |
| >= 0.5 | "Elevated {vector name} -- review before proceeding" |
| < 0.5 | "Minor {vector name} noted -- monitor" |

## Workflow: Sentinel as Risk Pre-Screen

```bash
# 1. Scan your planned change
3s sentinel "Adding Redis cache layer with distributed locks for the session store"

# 2. If risk is high/critical, escalate
3s cross-exam "Adding Redis cache with distributed locks for session store -- sentinel flagged concurrency and performance risks"

# 3. If risk is low/medium, proceed with awareness
# The triggered vectors tell you exactly where to focus your review
```

## Custom Vectors

The Sentinel accepts custom vectors programmatically:

```python
from three_surgeons.core.sentinel import Sentinel, ComplexityVector

custom_vectors = [
    ComplexityVector(
        id="CV-CUSTOM-001",
        name="Payment processing",
        keywords=["stripe", "payment", "charge", "refund", "invoice"],
        risk_score=0.9,
        noise_threshold=4,
    ),
]

sentinel = Sentinel(vectors=custom_vectors)
result = sentinel.run_cycle("Adding Stripe payment processing with automatic refunds")
```

This allows project-specific risk dimensions beyond the defaults.
