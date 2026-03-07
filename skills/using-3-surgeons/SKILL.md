---
name: using-3-surgeons
description: Bootstrap skill — teaches the 3-Surgeons multi-model consensus philosophy, surgeon roles, tool access, and when to invoke other skills
---

# Using 3-Surgeons

## Philosophy

**"The value is in the disagreements, not the agreements."**

Three LLMs with different training, different biases, and different blind spots cross-examine each other on critical decisions. Claude may confabulate confidently where GPT hedges. A local 4B model catches patterns that API models miss due to token limits. When all three agree, confidence is high. When they disagree, you have found the exact spot that needs human judgment.

## The Three Surgeons

| Surgeon | Model | Role | Cost |
|---------|-------|------|------|
| **Atlas** (Head Surgeon) | Claude (this session) | Synthesizes, decides, implements | $0 (session) |
| **Cardiologist** | GPT-4.1-mini (OpenAI API) | External perspective, cross-examination, evidence review | ~$0.40-1.60/1M tokens |
| **Neurologist** | Qwen3-4B (local Ollama/MLX) | Pattern recognition, corrigibility checks, classification | $0 (local) |

Atlas is always available -- it is the Claude session itself. The Cardiologist and Neurologist are external models accessed via the `3s` CLI or MCP tools.

## Constitutional Physics

These principles outrank all other preferences:

1. **Preserve Determinism** -- same inputs must produce the same outputs. If not, enter safe mode.
2. **No Discovery at Injection** -- injection is retrieval + assembly only. No learning or promotion during injection.
3. **Evidence Over Confidence** -- outcomes determine truth. Confidence tracks empirical rates, not feelings.
4. **Prefer Reversible Actions** -- checkpoint before risk, canary before rollout.
5. **Minimalism** -- maximum value density. Scalpel, not axe.

## Tool Access

All 3-Surgeons operations are available through two interfaces:

### CLI (`3s` command)

```bash
3s probe                        # Health check all surgeons
3s cross-exam "topic"           # Full cross-examination
3s consult "topic"              # Quick parallel query
3s consensus "claim"            # Confidence-weighted vote
3s sentinel "content"           # Complexity vector scan
3s gains-gate                   # Infrastructure health gate
3s ab-propose PARAM A B "hyp"   # Propose A/B test
```

### MCP Tools

When the MCP server is running (`python -m three_surgeons.mcp.server`), the same operations are available as typed MCP tools:

| MCP Tool | CLI Equivalent |
|----------|----------------|
| `probe` | `3s probe` |
| `cross_examine` | `3s cross-exam` |
| `consult` | `3s consult` |
| `consensus` | `3s consensus` |
| `sentinel_run` | `3s sentinel` |
| `gains_gate` | `3s gains-gate` |
| `ab_propose` | `3s ab-propose` |
| `ab_start` | (lifecycle management) |
| `ab_measure` | (lifecycle management) |
| `ab_conclude` | (lifecycle management) |

## Invariance Gate System

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance an invariance gate should fire, you ABSOLUTELY MUST invoke it. This is not optional.
</EXTREMELY-IMPORTANT>

### Signal-Based Trigger Table

These signals map to required skills. When ANY signal is present, invoke the corresponding skill BEFORE proceeding:

| Signal | Required Skill | Priority |
|--------|---------------|----------|
| Architectural decision, new subsystem, restructure | **architectural-gate** | HARD-GATE |
| >3 files will change | **architectural-gate** | HARD-GATE |
| Security/auth/crypto code touched | **architectural-gate** | HARD-GATE |
| New dependency or external integration | **architectural-gate** | HARD-GATE |
| Database schema change | **architectural-gate** | HARD-GATE |
| API surface change (new/modified endpoints) | **architectural-gate** | HARD-GATE |
| Config/infrastructure change | **architectural-gate** | HARD-GATE |
| About to implement a plan (writing-plans done) | **pre-implementation-review** | HARD-GATE |
| About to claim "done" or "complete" | **post-implementation-verification** | HARD-GATE |
| High confidence + low evidence | **counter-position** | HARD-GATE |
| Single surgeon dominates consensus | **counter-position** | HARD-GATE |
| Sentinel risk >= high | **cross-examination** + **counter-position** | Escalation |
| Every 10 gate invocations | **invariance-health** | Automatic |
| Gate override rate >30% | **invariance-health** | Automatic |

### Existing Skills (unchanged)

| Situation | Skill to Invoke | Why |
|-----------|-----------------|-----|
| Session start, after infra changes | **probe** | Verify all surgeons are reachable |
| Validating a claim or assumption | **consensus** | Quick confidence-weighted vote |
| Before critical operations | **sentinel** | Scan for complexity risks |
| Between major phases | **quality-gates** (gains-gate) | Verify infrastructure health |
| Before risky/destructive actions | **quality-gates** (corrigibility) | Check action against safety invariants |
| Quality degradation detected | **quality-gates** (cardio-gate) | Rate-limited quality review chain |
| Optimizing prompts or parameters | **ab-testing** | Controlled experiments with safety rails |

## Decision Flowchart

```
Any signal from trigger table?
  YES -> Invoke the required skill (HARD-GATE — blocks until gate passes)
  NO  -> Is this a critical decision?
    YES -> Does it affect >3 files or core architecture?
      YES -> cross-examination (full 3-phase)
      NO  -> consensus (quick weighted vote)
    NO  -> Is this a health/infra check?
      YES -> probe (connectivity) or gains-gate (full health)
      NO  -> Is this a complexity/risk assessment?
        YES -> sentinel (vector scan)
        NO  -> Proceed without surgeon consultation
```

## Invariance Workflow Chain

The full workflow when an architectural signal fires:

```
Signal detected
  → architectural-gate (risk stratification → Light/Standard/Full)
    → [brainstorming] (superpowers skill)
      → [writing-plans] (superpowers skill)
        → pre-implementation-review (HARD-GATE before coding)
          → [executing-plans] (superpowers skill)
            → post-implementation-verification (HARD-GATE before "done")
              → completion

Every 10 gates: invariance-health retrospective (metacognition)
```

This chain integrates with superpowers' process invariance. 3-Surgeons adds epistemological invariance (truth calibration) on top of superpowers' workflow discipline.

## Configuration

Config lives in `~/.3surgeons/config.yaml` or `.3surgeons.yaml` in the project root. Run `3s init` for interactive setup. See `config/3surgeons.example.yaml` for the full schema.

Key settings:
- `surgeons.cardiologist` -- OpenAI endpoint, model, API key env var
- `surgeons.neurologist` -- Ollama/MLX endpoint, model
- `budgets.daily_external_usd` -- daily spend cap (default $5)
- `budgets.autonomous_ab_usd` -- per-test cost cap (default $2)

## Evidence Store

All cross-examinations, cost tracking, A/B results, and learnings are persisted to `~/.3surgeons/evidence.db` (SQLite with FTS5). This provides institutional memory across sessions -- the system learns from its own decisions.

## Supported Providers

Any endpoint implementing the OpenAI `/v1/chat/completions` API works with zero code changes.

| Provider | Endpoint | Models | API Key Env | Cost |
|----------|----------|--------|-------------|------|
| **OpenAI** | `https://api.openai.com/v1` | gpt-4.1-mini, gpt-4.1, o3 | `OPENAI_API_KEY` | $0.10-8.00/1M |
| **DeepSeek** | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner | `DEEPSEEK_API_KEY` | $0.27-2.19/1M |
| **Groq** | `https://api.groq.com/openai/v1` | llama-3.3-70b, llama-3.1-8b | `GROQ_API_KEY` | $0.05-0.79/1M |
| **xAI (Grok)** | `https://api.x.ai/v1` | grok-2, grok-2-mini | `XAI_API_KEY` | $0.30-10.00/1M |
| **Mistral** | `https://api.mistral.ai/v1` | mistral-large, mistral-small | `MISTRAL_API_KEY` | $0.10-6.00/1M |
| **Ollama** | `http://localhost:11434/v1` | Any pulled model | none | $0 (local) |
| **LM Studio** | `http://localhost:1234/v1` | Any loaded model | none | $0 (local) |
| **vLLM** | `http://localhost:8000/v1` | Any served model | none | $0 (local) |

### Quick Provider Swap Examples

**DeepSeek as Neurologist** (cheap API, no local LLM needed):
```yaml
neurologist:
  provider: deepseek
  endpoint: https://api.deepseek.com/v1
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY
```

**Groq as Cardiologist** (ultra-fast inference):
```yaml
cardiologist:
  provider: groq
  endpoint: https://api.groq.com/openai/v1
  model: llama-3.3-70b-versatile
  api_key_env: GROQ_API_KEY
```

**Grok as Cardiologist** (xAI alternative):
```yaml
cardiologist:
  provider: xai
  endpoint: https://api.x.ai/v1
  model: grok-2
  api_key_env: XAI_API_KEY
```
