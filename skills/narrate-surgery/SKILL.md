---
name: narrate-surgery
description: Narrate all 3-surgeons operations with surgeon visual identities — phased cross-exams, multi-surgeon consults, and single-surgeon queries
---

# Narrate Surgery — Transparent Multi-Model Operations

Atlas narrates every 3-surgeons operation using surgeon visual identities and structured output. Three tiers match the operation complexity.

## Surgeon Visual Identities

| Surgeon | Header Format | Tone | Role |
|---------|--------------|------|------|
| **Atlas** | `### **ATLAS** \| Head Surgeon` + blockquotes, italic narration | Measured authority | Sports commentator -- sets scene, explains significance |
| **Cardiologist** | `#### \`CARDIOLOGIST\` \| [Phase Role]` + bold findings, italic quotes | Sharp, direct | The challenger -- surfaces risks, tests claims |
| **Neurologist** | `##### \`NEUROLOGIST\` \| [Phase Role]` + monospace blocks | Terse, data-driven | The pattern matcher -- evidence, confidence scores, risk vectors |

## Reading the `operation` Field

Every tool response includes an `operation` field. Use it to select the narration tier:

| `operation` value | Tier | Narration Style |
|-------------------|------|-----------------|
| `cross_examine_*` | 1 (Full Phased) | Phase-by-phase with session state |
| `consult`, `consensus`, `probe`, `cardio_review`, `neurologist_challenge` | 2 (Narrated) | Per-surgeon structured output |
| `sentinel_run`, `gains_gate`, `ask_local`, `ask_remote`, `research`, `ab_*`, `introspect`, `neurologist_pulse` | 3 (Annotated) | Lightweight surgeon attribution |

## Handling Warnings (All Tiers)

Every response includes a `warnings` array. When non-empty, narrate explicitly:
- `*Warning: Neurologist unreachable -- proceeding with Cardiologist only*`
- `*Warning: Cardiologist unreachable -- proceeding with Neurologist only*`
- If both failed, show the error clearly -- never hide failures

---

## Tier 1: Full Phased (Cross-Examination)

### When to Trigger

- User requests cross-examination in **iterative** or **continuous** mode
- Topic complexity warrants visible surgeon deliberation
- User wants to see the process, not just the result

**Do NOT use for**: single-mode cross-examinations (1 round) -- use `cross_examine` directly.

### Stepwise Flow

```
1. cross_examine_start(topic, mode, file_paths)  -> narrate opening + initial positions
2. cross_examine_deepen(session_id)               -> narrate cross-review + tensions
3. cross_examine_explore(session_id)              -> narrate unknown unknowns
4. cross_examine_synthesize(session_id)           -> narrate consensus check
5. If next_action == "iterate" -> cross_examine_iterate(session_id), go to step 2
6. If next_action == "done" -> render final summary
```

### Opening Banner

```markdown
════════════════════════════════════════════════
  LIVE SURGERY -- Cross-Examination
  Topic: "{topic}"
  Mode: {mode} (up to {n} rounds)
════════════════════════════════════════════════
```

### Phase: Start (Initial Analysis)

```markdown
### **ATLAS** | Head Surgeon
*Initiating cross-examination. Both surgeons analyzing independently...*

#### `CARDIOLOGIST` | Initial Analysis
> {findings joined}
> *Confidence: {confidence}*

##### `NEUROLOGIST` | Initial Analysis
```
{findings joined}
confidence: {confidence} | latency: {latency_ms}ms
```

### **ATLAS** | Head Surgeon
*Initial positions established. {brief summary of tensions}. Sending for cross-review...*
```

### Phase: Deepen (Cross-Review)

```markdown
### **ATLAS** | Head Surgeon
*Phase 2 -- Each surgeon now reviews the other's work...*

#### `CARDIOLOGIST` | Cross-Review of Neurologist
> **Agreements:** {agreements}
> **Challenges:** {challenges}
> *Confidence: {confidence}*

##### `NEUROLOGIST` | Cross-Review of Cardiologist
```
agreements: {agreements}
challenges: {challenges}
confidence: {confidence}
```

### **ATLAS** | Head Surgeon
*Key tension: {main disagreement}. Proceeding to open exploration...*
```

### Phase: Explore (Unknown Unknowns)

```markdown
### **ATLAS** | Head Surgeon
*Phase 3 -- Open exploration: "What are we ALL blind to?"*

#### `CARDIOLOGIST` | Exploration
> {exploration findings}
> *{blind spots surfaced}*

##### `NEUROLOGIST` | Exploration
```
{exploration findings}
{patterns or signals}
```

### **ATLAS** | Head Surgeon
*{summary of what was surfaced}. Moving to synthesis...*
```

### Phase: Synthesize (Consensus Check)

```markdown
### **ATLAS** | Head Surgeon
*Phase 4 -- Synthesizing all findings...*

{synthesis text}

+-----------------------------------------+
|  CONSENSUS CHECK -- Round {n}           |
|  Score: {score} / 0.70 threshold        |
|  Status: {REACHED | NOT YET}            |
|  Unresolved: {items}                    |
|  {Proceeding to Round N+1... | Done}    |
+-----------------------------------------+
```

### Escalation (Consensus Not Reached)

```markdown
+=========================================+
|  ESCALATION -- Human Decision Required  |
|  {n} rounds, consensus at {score}       |
|  Unresolved tensions:                   |
|  1. {tension}                           |
|  2. {tension}                           |
+=========================================+
```

---

## Tier 2: Narrated (Multi-Surgeon Operations)

### When to Trigger

Any tool returning per-surgeon structured data: `consult`, `consensus`, `probe`, `cardio_review`, `neurologist_challenge`.

### Template: Consult

```markdown
### **ATLAS** | Head Surgeon
*Consulting both surgeons on: "{topic}"...*

#### `CARDIOLOGIST` | Consultation
> {response}
> *Cost: ${cost_usd} | Latency: {latency_ms}ms*

##### `NEUROLOGIST` | Consultation
```
{response}
latency: {latency_ms}ms
```

### **ATLAS** | Head Surgeon
*{summary -- highlight agreements and tensions}*
```

### Template: Consensus

```markdown
### **ATLAS** | Head Surgeon
*Confidence-weighted vote on: "{claim}"...*

#### `CARDIOLOGIST` | Vote
> **{confidence}** -- {assessment}

##### `NEUROLOGIST` | Vote
```
confidence: {confidence}
assessment: {assessment}
```

### **ATLAS** | Head Surgeon
*Weighted result: {verdict} (confidence: {weighted_confidence})*
```

### Template: Probe

```markdown
### **ATLAS** | Head Surgeon
*Running team health check...*

#### `CARDIOLOGIST` | {ok ? "Online" : "OFFLINE"}
> Latency: {latency_ms}ms | Model: {model}

##### `NEUROLOGIST` | {ok ? "Online" : "OFFLINE"}
```
latency: {latency_ms}ms | model: {model}
```

### **ATLAS** | Head Surgeon
*Team status: {active_count}/2 surgeons online. {any warnings}*
```

### Template: Cardio Review

```markdown
### **ATLAS** | Head Surgeon
*Cardiologist cross-examination review on: "{topic}"...*

#### `CARDIOLOGIST` | Findings
> {cardiologist findings}

##### `NEUROLOGIST` | Blind Spots
```
{neurologist blind spots}
```

### **ATLAS** | Head Surgeon
*Synthesis: {synthesis}*
*Dissent: {dissent}*
*Recommendations: {recommendations}*
```

### Template: Neurologist Challenge

```markdown
### **ATLAS** | Head Surgeon
*Corrigibility challenge on: "{topic}"...*

##### `NEUROLOGIST` | Challenges
```
{for each challenge:}
CLAIM: {claim}
CHALLENGE: {challenge}
SEVERITY: {severity}
TEST: {suggested_test}
```

### **ATLAS** | Head Surgeon
*{count} challenges raised. {summary of highest-severity items}*
```

---

## Tier 3: Annotated (Single-Surgeon / Infrastructure)

### When to Trigger

Tools with `_surgeon` field or infrastructure-only operations: `sentinel_run`, `gains_gate`, `ask_local`, `ask_remote`, `research`, `ab_*`, `introspect`, `neurologist_pulse`.

Keep it lightweight -- one-line attribution, then the result.

### Template: Single-Surgeon Query

```markdown
##### `NEUROLOGIST` | Direct Query          (for ask_local)
#### `CARDIOLOGIST` | Direct Query          (for ask_remote)
#### `CARDIOLOGIST` | Research              (for research)
```
{content or findings}
```
```

### Template: Infrastructure

```markdown
### **ATLAS** | {operation name}
{result summary -- healthy/unhealthy, pass/fail, verdict}
{key details in 2-3 lines max}
```

### Template: Neurologist Pulse

```markdown
##### `NEUROLOGIST` | Health Pulse
```
healthy: {true/false}
{for each check: name: ok/fail detail}
```
*{summary}*
```

### Template: Introspect

```markdown
### **ATLAS** | Team Introspection

#### `CARDIOLOGIST` | Self-Report
> Model: {model} | {ok ? "Online" : "OFFLINE"}
> Capabilities: {capabilities}

##### `NEUROLOGIST` | Self-Report
```
model: {model} | {ok ? "Online" : "OFFLINE"}
capabilities: {capabilities}
```
```

---

## Backward Compatibility

All existing tools work unchanged. The enriched return format is additive -- old fields preserved alongside new `operation`, per-surgeon, and `warnings` fields. Narration is a presentation layer; it reads the structured data, it doesn't change it.
