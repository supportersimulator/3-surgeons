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
3s cross-exam "topic"           # Full cross-examination (uses config default mode)
3s cross-exam "topic" --mode iterative  # Cross-exam with explicit review depth
3s consult "topic"              # Quick parallel query
3s consensus "claim"            # Confidence-weighted vote
3s sentinel "content"           # Complexity vector scan
3s gains-gate                   # Infrastructure health gate
3s ab-propose PARAM A B "hyp"   # Propose A/B test
3s mode                         # Show current review depth + auto-depth setting
3s mode continuous              # Set default review depth
3s mode iterative --duration 7d # Set mode with expiry (session|7d|30d|permanent)
3s review-weights               # Show learned mode weights
3s review-weights show          # Same as above
3s review-weights export -o weights.json  # Export outcomes for sharing
3s review-weights import weights.json     # Import outcomes from another machine
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
| Cross-exam starting (any trigger) | **review-loop** | HARD-GATE |
| Every 10 gate invocations | **invariance-health** | Automatic |
| Gate override rate >30% | **invariance-health** | Automatic |

### Existing Skills

| Situation | Skill to Invoke | Why |
|-----------|-----------------|-----|
| Cross-exam about to start | **review-loop** | Selects review depth (single/iterative/continuous) based on risk |
| First run, surgeons not configured | **setup-team** | Head surgeon guides team assembly |
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
    → review-loop (selects depth: single/iterative/continuous)
      → [brainstorming] (superpowers skill)
        → [writing-plans] (superpowers skill)
          → pre-implementation-review (HARD-GATE before coding)
            → [executing-plans] (superpowers skill)
              → post-implementation-verification (HARD-GATE before "done")
                → completion

Every 10 gates: invariance-health retrospective (metacognition)
```

This chain integrates with superpowers' process invariance. 3-Surgeons adds epistemological invariance (truth calibration) on top of superpowers' workflow discipline.

## Review Loop Modes

Cross-examinations support three review depth modes that control how many iteration passes the surgeons make. The **review-loop** skill (see `skills/review-loop/SKILL.md`) fires as a HARD-GATE before every cross-exam to select the appropriate depth.

### Modes

| Mode | Max Iterations | When to Use |
|------|---------------|-------------|
| **single** | 1 | Config changes, docs, small fixes, <=2 files changed |
| **iterative** | up to 3 | Multi-file changes, new features, refactors (3-10 files) |
| **continuous** | up to 5 | Security, schema, API, architecture changes, >10 files |

### Mode Resolution Order

The mode used for a cross-exam is determined by (highest priority first):

1. **CLI `--mode` flag** -- `3s cross-exam "topic" --mode continuous`
2. **Config default** -- `review.depth` in `.3surgeons.yaml` or `~/.3surgeons/config.yaml`
3. **Adaptive weights** -- when `auto_review_depth: auto`, learned weights from past outcomes influence mode selection

### Risk Stratification Reference

When the review-loop skill auto-selects mode, it evaluates these dimensions. **The highest-risk dimension wins:**

| Dimension | single | iterative | continuous |
|-----------|--------|-----------|------------|
| Files changed | 1-2 | 3-10 | >10 |
| Reversibility | Fully reversible | Partially reversible | Hard to reverse |
| Security exposure | None | Internal | External/auth |
| Data impact | Read-only | Schema-preserving | Schema-changing |
| External coupling | None | Internal APIs | Public APIs |

### Exit Conditions

- **Consensus >= 0.7** on "all issues addressed" -- exits the loop early
- **Max iterations reached** without consensus -- escalates to human with unresolved summary
- **User override** at any point -- respected immediately

### Conversational Mode Switching

Users can set review depth through natural language. The agent maps intent to mode:

| User Says | Maps To |
|-----------|---------|
| "quick review", "just a glance" | single |
| "thorough review", "check carefully" | iterative |
| "loop until satisfied", "full depth", "keep going" | continuous |
| "3-surgeons full" | continuous |

### Managing Modes via CLI

```bash
# Show current mode and auto-depth setting
3s mode

# Set default depth (permanent unless --duration specified)
3s mode continuous
3s mode iterative --duration session   # Reverts after session ends
3s mode single --duration 7d           # Reverts after 7 days

# View learned weights from past review outcomes
3s review-weights

# Share weights across machines
3s review-weights export -o weights.json
3s review-weights import weights.json
```

### Auto-Depth Behavior

Controlled by the `auto_review_depth` config setting:

| Setting | Behavior |
|---------|----------|
| **off** | Always uses config default or CLI flag. No adaptation. |
| **suggest** | Recommends a mode with reasoning, waits for confirmation before proceeding. |
| **auto** | Applies learned weights from past outcomes. User can override anytime. |

## First-Run Setup

If the surgeons aren't configured yet, invoke the **setup-team** skill. It guides the user through assembling their team conversationally — detecting local backends, configuring API keys securely, and verifying connectivity. Low pressure, practical, gets the team running in under a minute.

## Configuration

Config lives in `~/.3surgeons/config.yaml` or `.3surgeons.yaml` in the project root. Run `3s init` for interactive setup, or use the **setup-team** skill for a guided experience. See `config/3surgeons.example.yaml` for the full schema.

Config merges across tiers: defaults → `~/.3surgeons/config.yaml` → `.3surgeons.yaml`. Each layer only overrides what it explicitly sets — unset fields inherit from the layer below. This means a project config only needs to specify what's different from your user-level config.

Key settings:
- `surgeons.cardiologist` -- endpoint, model, API key env var, optional `fallbacks` list
- `surgeons.neurologist` -- endpoint, model, optional `fallbacks` list
- `budgets.daily_external_usd` -- daily spend cap (default $5, enforced before external calls)
- `budgets.autonomous_ab_usd` -- per-test cost cap (default $2)

## Evidence Store

All cross-examinations, cost tracking, A/B results, and learnings are persisted to `~/.3surgeons/evidence.db` (SQLite with FTS5). This provides institutional memory across sessions -- the system learns from its own decisions.

## Supported Providers

Any endpoint implementing the OpenAI `/v1/chat/completions` API works with zero code changes.

| Provider | Endpoint | Models | API Key Env | Cost |
|----------|----------|--------|-------------|------|
| **OpenAI** | `https://api.openai.com/v1` | gpt-4.1-mini, gpt-4.1, o3 | `OPENAI_API_KEY` | $0.10-8.00/1M |
| **Anthropic** | `https://api.anthropic.com/v1` | claude-sonnet-4, claude-haiku-4.5 | `ANTHROPIC_API_KEY` | $0.80-15.00/1M |
| **Google** | `https://generativelanguage.googleapis.com/v1beta/openai` | gemini-2.5-pro, gemini-2.5-flash | `GOOGLE_API_KEY` | $0.15-10.00/1M |
| **DeepSeek** | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner | `DEEPSEEK_API_KEY` | $0.27-2.19/1M |
| **Groq** | `https://api.groq.com/openai/v1` | llama-3.3-70b, llama-3.1-8b | `GROQ_API_KEY` | $0.05-0.79/1M |
| **xAI (Grok)** | `https://api.x.ai/v1` | grok-2, grok-2-mini | `XAI_API_KEY` | $0.30-10.00/1M |
| **Mistral** | `https://api.mistral.ai/v1` | mistral-large, mistral-small | `MISTRAL_API_KEY` | $0.10-6.00/1M |
| **Cohere** | `https://api.cohere.com/v2` | command-r-plus, command-r | `COHERE_API_KEY` | $0.15-10.00/1M |
| **Perplexity** | `https://api.perplexity.ai` | sonar-pro, sonar | `PERPLEXITY_API_KEY` | $1.00-15.00/1M |
| **Together** | `https://api.together.xyz/v1` | Llama-3.3-70B, Llama-3.1-8B | `TOGETHER_API_KEY` | $0.18-0.88/1M |
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

**Cardiologist with automatic failover** (try OpenAI, fall back to DeepSeek):
```yaml
cardiologist:
  provider: openai
  endpoint: https://api.openai.com/v1
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY
  fallbacks:
    - provider: deepseek
      endpoint: https://api.deepseek.com/v1
      model: deepseek-chat
      api_key_env: DEEPSEEK_API_KEY
```
