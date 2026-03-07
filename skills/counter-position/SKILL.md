---
name: counter-position
description: HARD-GATE — invoke on architectural decisions, when confidence is high but evidence is low, or when a single surgeon dominates consensus. An opinion is NOT valid until you can argue BOTH sides.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - TodoWrite
---

# Counter-Position Protocol

## Philosophy

**An opinion is NOT valid until you can effectively argue BOTH sides.**

This is not debate for debate's sake. It is the core epistemological discipline: if you cannot steelman the opposition, you have not understood the problem deeply enough to decide. Confirmation bias is the failure mode this protocol exists to prevent.

<HARD-GATE>
Do NOT finalize any architectural decision until counter-position has been run. If you cannot construct a strong argument against your preferred position, your confidence is not earned.
</HARD-GATE>

## Auto-Invocation Triggers

| Signal | Why |
|--------|-----|
| Any architectural decision | Architectural choices are expensive to reverse |
| High confidence + low evidence | Confidence without evidence = confabulation |
| Single surgeon dominates consensus | Groupthink risk — the dissenting view needs construction |
| Sentinel risk >= high | High-risk changes deserve adversarial scrutiny |
| "Obviously" or "clearly" in reasoning | These words often mask unexamined assumptions |

## The 4-Step Protocol

You MUST create a TodoWrite task for each step:

### Step 1: State the Claim

What is being asserted? Write it as a clear, falsifiable statement.

**Good**: "We should use Redis sorted sets for the priority queue because they provide O(log N) insertion with built-in ordering."

**Bad**: "Redis is the right choice." (Too vague to counter — what aspect? Compared to what?)

### Step 2: Steelman the Opposition

Construct the **strongest possible argument AGAINST** the claim. This is not a strawman — it is the best case the other side could make.

Rules:
- Argue as if you genuinely believe the opposition
- Use the strongest evidence available, not the weakest
- Address the claim's actual strengths, not irrelevant weaknesses
- If you cannot construct a strong counter-argument, that IS evidence the claim is strong

### Step 3: Test the Opposition

Check the counter-argument against **actual code, evidence, and data**. This is where theory meets reality.

| Evidence Grade | Standard | Action |
|---------------|----------|--------|
| **Empirical** | Tested against running code/system | Trust — this is ground truth |
| **Documented** | Referenced in docs, specs, prior decisions | Trust — verified by prior work |
| **Analogical** | Pattern from similar systems/contexts | Consider — useful but not conclusive |
| **Theoretical** | Reasoning from principles without direct evidence | Investigate further before deciding |
| **Anecdotal** | Single observation or claim without verification | Do NOT decide based on this alone |

**Counter-position decisions MUST be backed by Empirical or Documented evidence.** Theoretical/Anecdotal evidence triggers additional investigation.

### Step 4: Decide with Evidence

Only after testing both sides, form a position:

- **If evidence clearly favors one side**: state the decision with evidence citations
- **If evidence is ambiguous**: present BOTH sides to Aaron with your assessment of the evidence quality
- **If evidence contradicts your initial position**: update your position. Corrigibility > confidence.

## Surgeon Integration

### Neurologist (Qwen3-4B)

Ask with code-specific framing:

```
You are part of a SOFTWARE DEVELOPMENT protocol called '3-surgeons'.
You are the local LLM (Qwen3-4B). We write CODE, not perform medical surgery.

CLAIM: [the assertion being tested]
COUNTER-ARGUMENT: [the steelmanned opposition]

YOUR ROLE: Classify which side has stronger pattern support based on the
code context provided. Look for: similar patterns in the codebase,
precedent from prior decisions, technical constraints that favor one side.

CODE CONTEXT: [relevant code snippets]
```

**Why domain anchoring**: Without explicit code-context framing, Qwen3-4B confabulates into medical neurology. Confirmed empirically: 3/3 false positives without anchoring, 7/7 actionable responses with anchoring.

### Cardiologist (GPT-4.1-mini)

Ask to cross-examine the evidence for both positions:

```
Cross-examine these two positions for a SOFTWARE DEVELOPMENT decision:

POSITION A: [the claim]
EVIDENCE A: [supporting evidence with grades]

POSITION B: [the counter-argument]
EVIDENCE B: [supporting evidence with grades]

Check for: logical consistency, cognitive biases (confirmation, anchoring,
availability), confidence calibration, and whether evidence grades are
accurately assigned.
```

The cardiologist's strengths to exploit here:
1. **Logical consistency scanning** — detect contradictions between claims and evidence
2. **Cognitive bias detection** — flag confirmation bias, anchoring, availability heuristic
3. **Confidence calibration** — flag overconfident claims with weak evidence

## Anti-Patterns

- **Strawman opposition**: Constructing a weak counter-argument you can easily defeat. If the opposition is easy to dismiss, you have not steelmanned it.
- **Cherry-picking evidence**: Selecting only evidence that supports your preferred position. Both sides get equal evidence scrutiny.
- **Anchoring on first opinion**: The first analysis (often Atlas's) anchors subsequent thinking. Counter-position exists to break this anchor.
- **Skipping Step 3**: Theoretical arguments feel convincing. They must be tested against code reality before deciding.
