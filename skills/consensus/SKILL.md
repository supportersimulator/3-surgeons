---
name: consensus
description: Confidence-weighted vote from multiple surgeons to validate claims and check assumptions
---

# Consensus

## When to Use

Consensus is the lightweight decision tool -- a quick confidence-weighted vote rather than a full cross-examination. Use it when:

- **Validating a claim** -- "Is this approach safe?" "Does this pattern follow best practices?"
- **Checking assumptions** -- before building on an assumption, verify it with both models
- **Pre-commit verification** -- "Will this change break backwards compatibility?"
- **Resolving simple disagreements** -- when you have two plausible options and need a tiebreaker
- **Quick sanity checks** -- "Is this the right data structure for this use case?"

**Do NOT use for**: complex architectural decisions (use cross-examination), health checks (use probe), or risk assessment (use sentinel).

## How to Invoke

### CLI

```bash
3s consensus "Redis LPUSH is O(1) for single elements"
```

### MCP Tool

```
consensus(claim="Redis LPUSH is O(1) for single elements")
```

## How It Works

Each surgeon receives the claim and responds with a JSON assessment:

```json
{
  "confidence": 0.85,
  "assessment": "agree",
  "reasoning": "Redis LPUSH is documented as O(1) per element..."
}
```

The system then calculates a weighted consensus score:

```
weighted_score = sum(confidence_i * assessment_value_i) / sum(confidence_i)
```

Where assessment values are: `agree = +1.0`, `uncertain = 0.0`, `disagree = -1.0`.

## Interpreting the Weighted Score

| Score Range | Meaning | Action |
|-------------|---------|--------|
| **+0.7 to +1.0** | Strong agreement | Proceed with confidence. Both surgeons agree the claim is valid. |
| **+0.3 to +0.7** | Moderate agreement | Proceed but verify. One surgeon is less confident or uncertain. |
| **-0.3 to +0.3** | Uncertain / Split | Do not proceed blindly. Consider escalating to full cross-examination. |
| **-0.7 to -0.3** | Moderate disagreement | The claim is likely wrong or oversimplified. Investigate further. |
| **-1.0 to -0.7** | Strong disagreement | The claim is rejected by both surgeons. Re-examine your assumption. |

## Reading Individual Assessments

The result includes each surgeon's individual vote:

```
Cardiologist: agree (confidence=0.90)
Neurologist:  uncertain (confidence=0.60)
Weighted score: +0.50
Total cost: $0.0008
```

Key things to notice:

- **Confidence asymmetry** -- if one surgeon is very confident (0.9) and the other is not (0.3), the confident vote dominates the weighted score. Check whether the less-confident model has a valid concern.
- **Assessment disagreement** -- one agrees, one disagrees. This is the most valuable signal. Why do they disagree? Escalate to cross-examination to find out.
- **Both uncertain** -- neither model has enough information. You may need to provide more context or rephrase the claim more specifically.

## When to Escalate to Cross-Examination

Escalate from consensus to full `cross-exam` when:

1. **Weighted score is in the uncertain zone** (-0.3 to +0.3) AND the decision is consequential
2. **Surgeons explicitly disagree** (one agrees, one disagrees) regardless of confidence levels
3. **Both are uncertain** with low confidence (<0.5) on a claim you need to act on
4. **The reasoning conflicts** -- even if both agree, check if their reasoning is compatible

Do NOT escalate when:
- Strong agreement on a low-stakes claim
- The uncertain zone is acceptable for a reversible action
- You already have external evidence (documentation, tests) that resolves the claim

## Cost

Consensus makes 2 LLM calls (one per surgeon). The Neurologist call is free (local model). The Cardiologist call costs approximately $0.0004-0.001 depending on claim length. This is roughly 1/5 the cost of a full cross-examination.

## Example Workflow

```bash
# Step 1: Quick consensus check
3s consensus "Switching from SQLite to PostgreSQL is safe for our <100 user base"
# Result: weighted_score=+0.45 (moderate, but uncertain zone edge)

# Step 2: Score is borderline -- escalate
3s cross-exam "Should we switch from SQLite to PostgreSQL given <100 concurrent users?"
# Result: Full analysis reveals Neurologist flagged WAL mode contention
# that Cardiologist missed, while Cardiologist noted migration complexity
```

The consensus caught that this was not a clear-cut decision. The cross-examination revealed exactly why.
