---
name: invariance-health
description: Metacognition — evaluate gate system effectiveness, calibrate thresholds, and fine-tune invariance
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - TodoWrite
---

# Invariance Health (Metacognition)

## Philosophy

**The gates evaluate themselves.**

A gate system that cannot assess its own effectiveness will either over-gate (delivery freeze) or under-gate (quality erosion). Neither failure mode is acceptable. This skill provides the feedback loop that keeps the invariance suite calibrated.

## Auto-Invocation Triggers

| Trigger | When |
|---------|------|
| Every 10 gate invocations | Automatic retrospective cycle |
| Aaron asks "how are the gates doing?" | On-demand health check |
| Gate override rate exceeds 30% | Signal that gates may be miscalibrated |
| Delivery velocity drops noticeably | Signal that gates may be over-blocking |
| Bug escapes to production | Signal that gates may be under-blocking |

## Metrics Tracked Per Gate Invocation

Log these to the evidence store (`~/.3surgeons/evidence.db`) for every gate run:

| Metric | What It Measures | Target |
|--------|-----------------|--------|
| **time_to_gate** | Total gate duration (seconds) | Light <30s, Standard <120s, Full <300s |
| **mode_selected** | Light/Standard/Full | Proportional to actual risk |
| **sentinel_risk** | Sentinel risk level output | Accurate reflection of true risk |
| **surgeon_agreement** | Did all 3 agree? (yes/partial/no) | Agreement on clear cases, disagreement on ambiguous |
| **gate_outcome** | pass/fail/bypass | Majority should pass (gates catch design issues, not block everything) |
| **override** | Did Aaron/Atlas override a finding? | Low rate (<15%) — high override = miscalibrated gate |
| **cost_usd** | LLM spend for this gate run | Light ~$0, Standard ~$0.003, Full ~$0.01 |
| **false_positive** | Gate blocked but change was fine (retrospective) | <20% — too many = delivery friction |
| **false_negative** | Gate passed but change caused issues (retrospective) | <5% — too many = gate not catching enough |

## 10-Invocation Retrospective

Every 10 gate invocations, run this analysis:

### Checklist

You MUST create a TodoWrite task for each step:

1. **Collect metrics from last 10 invocations** — query the evidence store for the 10 most recent gate entries. Calculate aggregates.

2. **Calculate false positive rate** — of the gates that blocked or flagged: how many were later shown to be unnecessary? Count cases where the flagged issue turned out to not be a problem.

3. **Calculate false negative rate** — of the gates that passed: how many changes later caused issues? Cross-reference with bug reports, rollbacks, or hotfixes that followed a passed gate.

4. **Cross-exam with cardiologist** — ask: "Given these 10 gate results, are we over-gating or under-gating? Is the risk stratification putting changes in the right modes?"

   ```
   You are part of a SOFTWARE DEVELOPMENT quality gate system.
   Here are the last 10 gate invocations with their outcomes:
   [data]

   Analyze: Are we over-gating (blocking good changes) or under-gating
   (passing bad changes)? Is the Light/Standard/Full mode selection
   accurate? What threshold adjustments would improve gate accuracy?
   ```

5. **Ask neurologist for pattern classification** — "Are certain change types consistently over-blocked or under-blocked?"

   ```
   You are part of a SOFTWARE DEVELOPMENT protocol called '3-surgeons'.
   You are the local LLM (Qwen3-4B). We write CODE, not perform medical surgery.

   Here are 10 gate invocations with mode, risk, and outcome:
   [data]

   YOUR ROLE: Classify patterns. Are certain types of changes
   (e.g., config changes, test additions) consistently assigned
   higher risk modes than their outcomes justify? Which change
   types are correctly calibrated?
   ```

6. **Propose threshold adjustments** — based on data, recommend specific calibration changes:
   - Should sentinel risk thresholds change?
   - Should mode selection criteria adjust?
   - Are certain gate steps consistently unhelpful and candidates for removal?
   - Should time-to-gate targets change?

7. **Present retrospective to Aaron** — summary with data and specific recommendations. Format:

   ```
   ## Invariance Health — 10-Invocation Retrospective

   **Period**: [date range]
   **Gate invocations**: 10
   **Pass rate**: X/10
   **Override rate**: X/10
   **Avg time-to-gate**: Xs (Light), Xs (Standard), Xs (Full)
   **Total cost**: $X.XX

   ### Calibration Assessment
   - False positive rate: X% (target <20%)
   - False negative rate: X% (target <5%)
   - Mode accuracy: X/10 changes were in the right mode

   ### Surgeon Assessment
   - Cardiologist: [over-gating / under-gating / well-calibrated]
   - Neurologist: [pattern findings]

   ### Recommendations
   1. [specific adjustment with data backing]
   2. [specific adjustment with data backing]
   ```

## Feedback Loop

Recommendations from invariance-health feed back into the system:

```
gate invocations → evidence store → invariance-health analysis
                                          ↓
                                    recommendations
                                          ↓
                        architectural-gate risk stratification
                        sentinel threshold adjustments
                        mode selection criteria updates
```

**The system learns from its own gating decisions.** This is not static configuration — it evolves based on empirical outcomes.

## Real-Time Signals (supplement to retrospectives)

The cross-exam raised a valid point: 10-invocation retrospectives are purely retrospective. To catch fast-evolving issues, also monitor these real-time signals:

| Signal | Detection | Action |
|--------|-----------|--------|
| 3 consecutive overrides | Evidence store query | Trigger early retrospective |
| Gate time exceeds 2x target | Timer in gate execution | Flag for investigation |
| Surgeon disagreement rate >50% over 5 invocations | Evidence store query | Trigger cross-exam on the gate system itself |
| Zero gates in 48h despite active development | Absence detection | Are gates being silently skipped? |

## What NOT to Do

- **Do NOT adjust thresholds without data** — gut feelings about "too much gating" are not evidence. Run the metrics first.
- **Do NOT remove gate steps based on a single retrospective** — look for consistent patterns across multiple cycles before removing steps.
- **Do NOT optimize for speed at the expense of catch rate** — the goal is calibrated gating, not fast gating.
- **Do NOT ignore the metacognition layer** — if invariance-health stops running, the gates become static and will drift from reality.
