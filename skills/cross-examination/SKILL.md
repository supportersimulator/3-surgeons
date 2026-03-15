---
name: cross-examination
description: Deep 3-phase multi-model analysis — cross-examine a claim using multiple AI models
---

# Cross-Examination

## When to Trigger

Cross-examination is the heavyweight tool. Use it when the stakes justify the cost and latency:

- **Major architectural decisions** -- changing core data flow, adding new subsystems, restructuring modules
- **Conflicting evidence** -- two sources disagree, logs contradict expectations, behavior is non-deterministic
- **High-risk changes** -- touching authentication, payment flows, safety systems, production data
- **Wide-impact changes** -- modifying >3 files, changing shared interfaces, altering database schemas
- **Persistent bugs** -- root cause unclear after 15+ minutes of investigation

**Do NOT use for**: trivial fixes, style changes, single-file edits with clear scope, questions with obvious answers.

## How to Invoke

### CLI

```bash
3s cross-exam "Should we migrate from REST to GraphQL for the patient API?"
```

### MCP Tool

```
cross_examine(topic="Should we migrate from REST to GraphQL for the patient API?", depth="full")
```

The `depth` parameter defaults to `"full"` (3-phase). There is currently one depth level; future versions may support `"quick"`.

## The 3-Phase Process

### Phase 1: Independent Analysis

Both the Cardiologist (GPT-4.1-mini) and Neurologist (Qwen3-4B) analyze the topic independently. Neither sees the other's work. This prevents anchoring bias -- each model forms its own opinion from scratch.

### Phase 2: Cross-Review

Each surgeon reviews the other's Phase 1 analysis. The Cardiologist reviews the Neurologist's work, looking for weaknesses, blind spots, and errors. The Neurologist does the same for the Cardiologist. This adversarial review is where most value is generated.

### Phase 3: Synthesis

The Cardiologist (broader perspective from the external API model) synthesizes both analyses and both cross-reviews into a final report. The synthesis explicitly emphasizes **disagreements** -- where the surgeons diverge is the most valuable signal.

## Interpreting Results

The result contains four key fields:

| Field | What It Tells You |
|-------|-------------------|
| `cardiologist_report` | Initial analysis + cross-review of neurologist's work |
| `neurologist_report` | Initial analysis + cross-review of cardiologist's work |
| `synthesis` | Combined view emphasizing disagreements |
| `total_cost` | USD spent on external API calls |

### Reading the Synthesis

1. **Look for disagreements first.** Agreements are low-value -- both models trained on similar data will often agree on easy questions. The disagreements are where your decision actually matters.
2. **Weight by model strengths.** The Cardiologist (GPT-4.1-mini) is stronger on broad reasoning and world knowledge. The Neurologist (Qwen3-4B) is better at pattern matching and catching subtle local issues.
3. **Check the cross-reviews.** Each surgeon's cross-review section (marked `--- Cross-Review ---`) highlights what the other missed. These blind spots are the highest-value findings.

### Example Output Structure

```
--- Cardiologist ---
[Initial analysis of the topic]

--- Cross-Review ---
[Cardiologist's critique of Neurologist's analysis]

--- Neurologist ---
[Initial analysis of the topic]

--- Cross-Review ---
[Neurologist's critique of Cardiologist's analysis]

--- Synthesis ---
[Combined findings, disagreements highlighted]

Cost: $0.0042 | Latency: 3200ms
```

## What NOT to Do

- **Do NOT ignore disagreements.** If the synthesis says the surgeons disagree, investigate that specific point. The disagreement IS the answer.
- **Do NOT cherry-pick.** If you already had an opinion and one surgeon agrees while the other disagrees, you must genuinely consider the dissenting view. Confirmation bias is the failure mode this system is designed to prevent.
- **Do NOT override without evidence.** Atlas (Claude) synthesizes but does not override. If you disagree with both surgeons, state your reasoning explicitly and present all three views to the human for the final call.
- **Do NOT run on trivial topics.** Each full cross-exam makes ~5 LLM calls across two models. Reserve it for decisions that justify the cost (~$0.003-0.01 per run).

## Graceful Degradation

If one surgeon is unavailable (endpoint down, timeout), the cross-examination still completes with the available surgeon. The result will have `None` for the missing surgeon's report. This is expected -- a one-surgeon analysis is still better than no analysis. Run `3s probe` if a surgeon is persistently unavailable.

## Evidence Trail

Every cross-examination is automatically logged to the evidence store (`~/.3surgeons/evidence.db`). This means:
- You can search past cross-exams by topic
- Cost is tracked per surgeon per operation
- The system builds institutional memory over time

## Quick Alternative: Consult

If you need both surgeons' opinions but do NOT need cross-review or synthesis, use `3s consult "topic"` instead. This runs Phase 1 only (independent analysis) at roughly 1/3 the cost and latency.
