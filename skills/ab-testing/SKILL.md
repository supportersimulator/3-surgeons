---
name: ab-testing
description: Invoke when optimizing prompts, comparing approaches, or tuning parameters -- manages the full A/B test lifecycle with safety constraints and human veto windows
---

# A/B Testing

## When to Propose an A/B Test

A/B testing is for controlled experiments where you have two plausible approaches and want empirical evidence for which performs better. Use it when:

- **Optimizing prompts** -- "Does system prompt A produce better results than system prompt B?"
- **Comparing approaches** -- "Is caching strategy X faster than strategy Y?"
- **Parameter tuning** -- "Does temperature=0.3 produce more consistent output than temperature=0.7?"
- **Validating improvements** -- "Does the refactored code actually perform better than the original?"

**Do NOT use for**: safety-critical parameters, authentication settings, cost/rate limits, or anything that could compromise system integrity. These are enforced as forbidden parameters (see Safety Constraints below).

## The Full Lifecycle

An A/B test moves through these states:

```
PROPOSED -> GRACE_PERIOD -> ACTIVE -> MONITORING -> CONCLUDED
                |                                       |
                v                                       v
             VETOED                                 REVERTED
                                                (auto: cost/time exceeded)
```

### Step 1: Propose

```bash
3s ab-propose "temperature" "0.3" "0.7" "Lower temperature produces more consistent classification output"
```

Or via MCP:

```
ab_propose(
    param="temperature",
    variant_a="0.3",
    variant_b="0.7",
    hypothesis="Lower temperature produces more consistent classification output"
)
```

This creates the test in `PROPOSED` status and returns a test ID (UUID). The test is not yet running.

### Step 2: Grace Period (Human Veto Window)

```
ab_start(test_id="<uuid>")
```

Moves the test to `GRACE_PERIOD`. This is a deliberate pause (default 30 minutes) that allows a human to review the proposal and veto it before any resources are spent. The grace period duration is informational -- enforcement is the caller's responsibility.

**Why a grace period?** Autonomous A/B testing without human oversight can waste budget on ill-conceived experiments. The grace period is a safety valve.

### Step 3: Activate

```
ab_start -> (wait for grace period) -> activate(test_id="<uuid>")
```

Activation requires the test to be in `GRACE_PERIOD`. If the test was vetoed during the grace period, activation will fail. Once active, the experiment is running.

### Step 4: Measure

```
ab_measure(test_id="<uuid>", metric_a=0.85, metric_b=0.92)
```

Records a measurement pair. Returns a comparison:

```json
{
    "test_id": "<uuid>",
    "metric_a": 0.85,
    "metric_b": 0.92,
    "delta": 0.07,
    "variant_b_better": true
}
```

You can record multiple measurements over the test duration.

### Step 5: Conclude

```
ab_conclude(test_id="<uuid>", verdict="Variant B (0.7) produced 7% higher accuracy; adopting as default")
```

Records the verdict in the evidence store for future reference. The test moves to `CONCLUDED` status.

### Alternative: Veto

At any point before conclusion, a test can be vetoed:

```bash
# Not yet exposed via CLI -- use MCP or programmatic API
```

Vetoed tests are marked with the reason and move to terminal `VETOED` status.

## Safety Constraints

### Forbidden Parameters

The following parameters cannot be A/B tested. Attempting to propose a test on them raises a `ValueError`:

| Parameter | Reason |
|-----------|--------|
| `safety_gate` | Could disable safety checks |
| `corrigibility` | Could weaken safety invariants |
| `evidence_retention` | Could erase institutional memory |
| `cost_limit` | Could remove spending guardrails |
| `rate_limit` | Could allow resource exhaustion |

Additionally, any parameter containing `"security"` or `"auth"` (case-insensitive) is automatically forbidden.

### Budget Caps

Each test has two automatic limits:

| Limit | Default | What Happens |
|-------|---------|-------------|
| `max_cost_usd` | $2.00 (from `budgets.autonomous_ab_usd`) | Test auto-reverts to `REVERTED` status |
| `max_duration_hours` | 48 hours | Test auto-reverts to `REVERTED` status |

These limits are checked via `check_safety(test_id)`. When exceeded, the test is automatically moved to `REVERTED` with a verdict explaining why.

### Daily Budget

The overall daily external spend cap (`budgets.daily_external_usd`, default $5) applies across all A/B tests and other external LLM calls.

## Querying Active Tests

```python
# Programmatic -- returns all non-terminal tests
engine.get_active_tests()

# Check a specific test
engine.get_test(test_id)
```

Active tests are those not in `CONCLUDED`, `VETOED`, or `REVERTED` status.

## Evidence Integration

When a test is concluded, the result is automatically recorded in the evidence store:

- **`ab_results` table**: experiment ID, param, variants, verdict
- **`cost_tracking` table**: total cost attributed to the test
- **Searchable**: future evidence queries can surface past A/B results

This means if you later ask "What temperature setting works best?", the evidence store can return past A/B test results on that parameter.

## Example: Full Workflow

```bash
# 1. Propose
3s ab-propose "prompt_style" "concise" "detailed" "Concise prompts reduce token usage without quality loss"
# Output: A/B test proposed: a1b2c3d4-...

# 2. Start grace period (via MCP tool)
# ab_start(test_id="a1b2c3d4-...")
# Wait 30 minutes for human review

# 3. Activate (via MCP tool)
# activate(test_id="a1b2c3d4-...")

# 4. Run both variants, measure results
# ab_measure(test_id="a1b2c3d4-...", metric_a=0.82, metric_b=0.79)
# ab_measure(test_id="a1b2c3d4-...", metric_a=0.85, metric_b=0.80)

# 5. Conclude with verdict
# ab_conclude(test_id="a1b2c3d4-...", verdict="Variant A (concise) 4% better on avg; adopting")
```
