<div align="center">

<img src="icon.png" alt="3-Surgeons — three AI surgeons cross-examining your code" width="200" />
<!-- TODO: swap for docs/assets/3-surgeons-banner.png once a wide banner is ready -->

# 3-Surgeons

**Three independent AI models. Cross-examined consensus. Your code ships when all three agree.**

Three surgeons, one operating table. Built on five Constitutional Physics invariants and a four-phase operating protocol. **Disagreements are signal, not noise** — and the protocol is provider-agnostic across OpenAI, DeepSeek, Anthropic, Ollama, LM Studio, vLLM, and MLX.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Providers](https://img.shields.io/badge/providers-OpenAI%20%7C%20DeepSeek%20%7C%20Ollama%20%7C%20MLX-27aae1.svg)](#provider-compatibility)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-7c3aed.svg)](https://claude.com/claude-code)
[![Corrigibility](https://img.shields.io/badge/Corrigibility-invariant-success.svg)](#why-it-works-corrigibility)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

[**Quick Start**](#quick-start) · [**Constitutional Physics**](#constitutional-physics) · [**Install**](#install) · [**IDE Compatibility**](#ide-compatibility) · [**Pairs With**](#pairs-with-superpowers-plugin)

</div>

---

> Would you wing a complicated surgery with one surgeon?
>
> Then why are you shipping code reviewed by one AI?

## The Problem

Every AI coding tool has the same flaw: **one model, one perspective, one set of blind spots.** Claude confabulates confidently where GPT hedges. GPT over-engineers where a local model stays lean. A single AI reviewer is a single point of failure — and you'd never accept that in a real operating room.

## The Solution

3-Surgeons puts three independent AI models on the same operating table. They don't just review — they **cross-examine**, challenge assumptions, and hunt for what the others missed. Your code ships only when all three agree it's ready.

| | Surgeon | Role | Default Model |
|---|---------|------|---------------|
| 🔪 | **Head Surgeon** | Synthesizes, decides, implements | Claude (your IDE session) |
| 🩺 | **Cardiologist** | External perspective, cross-examination | GPT-4.1-mini (OpenAI) |
| 🧠 | **Neurologist** | Pattern recognition, corrigibility checks | Qwen3-4B (local, private) |

---

## The Vision: Calibrated Correctness at Any Scale

> A single AI reviewer is a single point of failure. Three reviewers, hunting independently, force the truth into the open.

3-Surgeons is built on one belief: **the bottleneck in AI-assisted coding is no longer speed — it's calibration.** A confidently wrong answer ships faster than a careful right one. Three independent surgeons make confidence *earnable* — every claim survives cross-examination or it dies on the table.

| Scale | What it unlocks |
|-------|-----------------|
| **1 model** | One opinion. Fast. Possibly wrong, but you wouldn't know. |
| **2 models** | A check. Often agree. Disagreement = stop and look. |
| **3 models** | Triangulation. Truth becomes recoverable. The blind spot of any one model is exposed by the other two. |
| **5+ models** | A specialty board. Each surgeon brings a different training distribution. Convergence under independent attack is *evidence*, not opinion. |
| **Continuous review** | Every diff cross-examined. Every claim audited. Every blind spot named. Calibration compounds across the codebase. |

The protocol scales linearly with the number of surgeons. The architecture is provider-agnostic. **The only ceiling is your tolerance for groupthink.**

---

## Constitutional Physics

Five principles that govern every surgical operation. These are invariants — no tool call, no config flag, no shortcut overrides them.

| # | Principle | What it means |
|---|-----------|----------------|
| 1 | **Preserve Determinism** | Same inputs must produce the same output. Non-deterministic paths trigger safe mode and are flagged before shipping. |
| 2 | **No Discovery at Injection** | Retrieval only during context injection — no new reasoning, no live inference. Prevents hallucinations from contaminating shared state. |
| 3 | **Respect SOP Integrity** | Standard Operating Procedures change only when backed by reproducible evidence from at least two surgeons. Opinion alone is not enough. |
| 4 | **Evidence Over Confidence** | Outcomes are the ground truth. A confident answer that contradicts observed behavior is wrong. |
| 5 | **Prefer Reversible Actions** | Checkpoint before risk. Every destructive or irreversible action requires explicit surgeon consensus and a rollback path. |

## Why It Works: Corrigibility

Most AI tools optimize for **confidence**. 3-Surgeons optimizes for **correctness**.

The core principle: **no surgeon can conclude an opinion until an objective test of the opposing view yields legitimate data — only then is the opinion merited.**

This isn't just "get a second opinion." It's an iterative consensus loop:

1. **Each surgeon hunts independently** — different prompts, different search strategies, different biases
2. **Cross-examination** — each surgeon reviews the others' findings and challenges weak points
3. **Open exploration** — "What are we ALL blind to? What assumptions remain unchallenged?"
4. **Consensus only when saturated** — disagreements are preserved, not suppressed

Feel the difference between code that was *generated* and code that **survived**.

## The 4-Phase Operating Protocol

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌───────────┐
│  1. TRIAGE   │───▶│  2. OPERATE   │───▶│  3. REVIEW   │───▶│  4. CLOSE  │
│  Assess risk │    │  Independent  │    │  Cross-exam  │    │  Consensus │
│  Set gates   │    │  analysis     │    │  Challenge   │    │  or dissent│
└─────────────┘    └──────────────┘    └─────────────┘    └───────────┘
```

**Triage** — Sentinel scans your change for complexity vectors and calibrates review intensity.
**Operate** — Each surgeon analyzes independently. No groupthink.
**Review** — Cross-examination. Each surgeon attacks the others' blind spots.
**Close** — Consensus with confidence scores. Disagreements surfaced, never hidden.

## Blast Radius Calibration

Not every change needs a full surgery. 3-Surgeons adapts review intensity to risk:

| Risk Level | Gate Intensity | When | Time |
|------------|---------------|------|------|
| **Light** | Sentinel scan only | Docs, config, cosmetic changes | <30s |
| **Standard** | Sentinel + cross-exam + gains-gate | Feature work, refactors | <120s |
| **Full** | All gates + counter-position + A/B | Architecture, security, schema, API changes | <300s |

Risk is measured across blast radius, reversibility, security exposure, data impact, and external coupling. The highest-risk dimension determines the gate.

## Prerequisites

**Python 3.10+** is required for the MCP server (cross-examination tools in your IDE).

```bash
# Check your version
python3 --version

# If below 3.10, install via Homebrew (macOS)
brew install python@3.12

# Or via pyenv (any platform)
pyenv install 3.12
pyenv global 3.12
```

The `3s init` wizard will check your Python version and guide you if it's too old.

## Quick Start

```bash
# 1. Install (Claude Code)
/plugin marketplace add supportersimulator/3-surgeons
/plugin install 3-surgeons@supportersimulator/3-surgeons

# 2. Run the setup wizard
3s init

# 3. Set your API key(s)
export OPENAI_API_KEY=sk-...

# 4. Verify all surgeons are reachable
3s probe

# 5. Your first cross-examination
3s cross-exam "Should we use Redis or PostgreSQL for session storage?"
```

## Install

### Claude Code (Marketplace)

```bash
/plugin marketplace add supportersimulator/3-surgeons
/plugin install 3-surgeons@supportersimulator/3-surgeons
```

### VS Code (Agent Plugin — requires 1.110+)

> **Important:** This uses VS Code's Agent Plugin system (Chat panel), NOT the traditional Extension Marketplace. You will NOT find it by searching in the Extensions sidebar.

**Step 1: Install GitHub Copilot Chat**

Install the **GitHub Copilot Chat** extension from the VS Code Marketplace (not the legacy "GitHub Copilot" extension). Sign into GitHub with a Copilot-entitled account.

**Step 2: Enable plugins and add the marketplace**

Open Settings (`Cmd+,` / `Ctrl+,`) and add these to your `settings.json`:

```json
{
  "chat.plugins.enabled": true,
  "chat.plugins.marketplaces": ["supportersimulator/3-surgeons"]
}
```

**Step 3: Reload and verify**

1. Reload window (`Cmd+Shift+P` → "Developer: Reload Window")
2. Open the **Chat panel** (not Extensions sidebar)
3. Type `@agentPlugins` to verify the plugin appears

**Step 4: Set up the Python runtime**

The MCP tools need Python 3.10+ with the package installed:

```bash
git clone https://github.com/supportersimulator/3-surgeons.git ~/3-surgeons
cd ~/3-surgeons
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
```

**Local path fallback** (if marketplace discovery doesn't resolve):

Add the cloned path directly in `settings.json`:

```json
{
  "chat.plugins.paths": {
    "/Users/you/3-surgeons": true
  }
}
```

### Cursor

```bash
cursor plugin add supportersimulator/3-surgeons
```

### Codex CLI / Codex IDE Extension

```bash
git clone https://github.com/supportersimulator/3-surgeons.git ~/.3surgeons/plugin
cd ~/.3surgeons/plugin
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
codex mcp add 3-surgeons -- ~/.3surgeons/plugin/bin/3surgeons-mcp
```

See [CODEX.md](CODEX.md) for full setup, config options, and troubleshooting.

### Gemini CLI

```bash
gemini extensions install https://github.com/supportersimulator/3-surgeons
```

See [GEMINI.md](GEMINI.md) for full setup, backend configuration, and troubleshooting.

### Manual (any IDE)

```bash
git clone https://github.com/supportersimulator/3-surgeons.git ~/.claude/plugins/3-surgeons
cd ~/.claude/plugins/3-surgeons
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
```

## IDE Compatibility

| IDE | Transport | Status |
|-----|-----------|--------|
| Claude Code | MCP (native) | ✅ Full support |
| Cursor | HTTP bridge | ✅ Full support |
| VS Code | HTTP bridge | ✅ Full support |
| Windsurf | HTTP bridge | ✅ Full support |
| Zed | HTTP bridge | ✅ Full support |
| OpenCode | HTTP bridge | ✅ Full support |
| Codex CLI / IDE | MCP (native) | ✅ Full support — see [CODEX.md](CODEX.md) |
| Gemini CLI | MCP (extension) | ✅ Full support — see [GEMINI.md](GEMINI.md) |

All tools available via `3s serve` HTTP bridge. See `three_surgeons/config/ide-adapters/` for per-IDE configuration.

## Three Modes

| Mode | Cardiologist | Neurologist | Needs | Cost |
|------|-------------|-------------|-------|------|
| **Hybrid** (default) | OpenAI GPT-4.1-mini | Local Ollama qwen3:4b | 1 API key + Ollama | ~$0.003/query |
| **API-Only** | OpenAI GPT-4.1-mini | DeepSeek deepseek-chat | 2 API keys | ~$0.005/query |
| **Local-Only** | Ollama mistral:7b | Ollama qwen3:4b | Ollama installed | $0 |

Run `3s init` to pick a mode, or copy a preset directly:

```bash
cp config/presets/api-only.yaml ~/.3surgeons/config.yaml
```

## Provider Compatibility

Any endpoint implementing OpenAI's `/v1/chat/completions` API works with zero code changes:

**Cloud:** OpenAI, DeepSeek, Groq, Grok (xAI), Mistral

**Local:** Ollama, LM Studio, vLLM, MLX

See the [full provider matrix](skills/using-3-surgeons/SKILL.md#supported-providers) for endpoints, models, and pricing.

## Commands

| Command | Description |
|---------|-------------|
| `/probe` | Health check all three surgeons |
| `/cross-exam` | Full 3-phase cross-examination |
| `/sentinel` | Scan for complexity risk vectors |
| `/gains-gate` | Infrastructure health gate |
| `/challenge` | Neurologist corrigibility skeptic |

## CLI

```bash
3s probe                        # Health check
3s cross-exam "topic"           # Full cross-examination
3s consult "topic"              # Quick parallel query
3s consensus "claim"            # Confidence-weighted vote
3s sentinel "content"           # Complexity vector scan
3s gains-gate                   # Infrastructure health gate
3s neurologist-challenge "topic" # Corrigibility skeptic
3s ask-local "prompt"           # Direct neurologist query
3s ask-remote "prompt"          # Direct cardiologist query
3s research "topic"             # Self-directed research
3s ab-propose PARAM A B "hyp"   # Propose A/B test
```

## Orchestration Chains

Compose surgical operations into named, replayable chains:

```bash
3s chain run full-review        # Run a named chain preset
3s chain list                   # Show available presets
3s chain show full-review       # Inspect chain segments
```

Built-in presets: `full-review`, `quick-check`, `deep-audit`, `pre-merge`, `security-scan`. Chains are capability-adaptive — segments that require unavailable surgeons gracefully degrade or skip.

## Configuration

Config lives in `~/.3surgeons/config.yaml` (user-level) or `.3surgeons.yaml` (project-level).

Run `3s init` for guided setup, or copy a preset from `config/presets/`.

See `config/3surgeons.example.yaml` for the full schema.

### Cardiologist Provider (OpenAI | DeepSeek)

The Cardiologist defaults to **OpenAI `gpt-4.1-mini`**. DeepSeek is a drop-in alternative — it speaks the same OpenAI-compatible `/v1/chat/completions` wire protocol, so no adapter changes are required.

**Per-invocation CLI flag** (preserves backward-compat defaults):

```bash
3s --cardio-provider=deepseek cross-exam "your topic"
3s --cardio-provider=openai probe            # explicit default
```

When `--cardio-provider=deepseek` is set, the Cardiologist routes to `https://api.deepseek.com/v1` with model `deepseek-chat`. Common OpenAI model strings auto-translate:

| OpenAI model | DeepSeek equivalent |
|---|---|
| `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-4.1-nano`, `gpt-4.1` | `deepseek-chat` |
| `o1-mini`, `o3-mini`, `o4-mini` | `deepseek-reasoner` |

**Persistent YAML config:**

```yaml
surgeons:
  cardiologist:
    provider: deepseek
    endpoint: https://api.deepseek.com/v1
    model: deepseek-chat           # or deepseek-reasoner for o1-style reasoning
    api_key_env: Context_DNA_Deepseek
```

Or copy the ready-made preset:

```bash
cp config/presets/cardio-deepseek.yaml ~/.3surgeons/config.yaml
```

**API key resolution order (DeepSeek):**

1. The env var named in `api_key_env` (default `Context_DNA_Deepseek`)
2. `DEEPSEEK_API_KEY` (fallback — matches `/ersim/prod/backend/DEEPSEEK_API_KEY` in AWS Secrets Manager and `.env.example`)
3. macOS Keychain via the 3-Surgeons MCP launcher (`3surgeons-mcp`)

If none are set and `--cardio-provider=deepseek` requires a live call, the CLI fails fast with an actionable message naming both env vars.

**Status reporting:** `cap_status` / `3s status` surfaces the active provider under `surgeons.cardiologist.provider`, so IDE dashboards can render `Cardiologist: OK [deepseek]` vs `[openai]`.

**Default unchanged:** omitting `--cardio-provider` and leaving `surgeons.cardiologist.provider` at its default preserves the original OpenAI `gpt-4.1-mini` behavior — no migration required.

## Security

- **All API keys are loaded from environment variables** — never hardcoded, never committed
- **Local-Only mode**: zero data leaves your machine. The Neurologist runs entirely on your hardware
- `.gitignore` excludes all secret files, config files, and databases
- See `.env.example` for the full list of supported environment variables

## Pairs With: Superpowers Plugin

3-Surgeons provides the **epistemological layer** (truth calibration through multi-model consensus). The [Superpowers](https://github.com/supportersimulator/superpowers) plugin provides the **process layer** (workflow discipline, TDD, debugging, planning skills). Together they form a complete surgical operating environment — rigorous process AND rigorous truth-testing.

## Pairs With: Multi-Fleet

3-Surgeons is the *quality* dimension. [**Multi-Fleet**](https://github.com/supportersimulator/multi-fleet) is the *scale* dimension. Run 3-Surgeons on a single machine and you get calibrated correctness. Run it across a Multi-Fleet of N machines and every surgeon-trio shares findings via NATS — disagreements surface fleet-wide, consensus compounds across nodes. **Correctness × scale = a coding board of directors that never sleeps.**

---

## ContextDNA: The Full Operating Theater

3-Surgeons works standalone. But it was built to be the scalpel in a much larger operating theater.

**ContextDNA** adds persistent memory, a priority-scheduled local LLM (your Neurologist on steroids), adaptive webhook injection, and a butler subconscious that learns your codebase across sessions. Think of it as upgrading from a field hospital to a world-class surgical suite.

*3-Surgeons adapts to the sophistication of your codebase.*

When you're ready:

```python
from context_dna.adapters import priority_queue_adapter
provider = LLMProvider(config, query_adapter=priority_queue_adapter)
```

See [docs/CONTEXTDNA-IDE-UPGRADE.md](docs/CONTEXTDNA-IDE-UPGRADE.md) for the full migration guide.

## Why Disagreements = Value

When all three surgeons agree immediately, that is a weak signal — it may mean groupthink, not correctness. When they disagree, that is the system working.

A disagreement surfaces:
- An assumption one model holds that the others don't
- A risk one model has been trained to weight differently
- A blind spot in the majority view

3-Surgeons never suppresses disagreements. Confidence scores in the final consensus output show exactly where the surgeons diverged and why. The human (or orchestrating agent) decides what to do with that signal — but they decide with full information.

**The goal is not fast consensus. The goal is calibrated confidence.**

## Contributing

1. Fork the repo
2. Create a feature branch
3. Run tests: `python -m pytest tests/ -v`
4. Submit a PR

## Status

3-Surgeons is **production-tested at small scale**. It powers the daily review loop on a 4-node ContextDNA fleet (mac1, mac2, mac3, cloud) — every commit, every cross-examination, every consensus claim ships through the protocol. It has survived provider outages, model deprecations, and partial-network partitions without dropping a verdict.

It is **deliberately scoped**: 3-Surgeons does cross-examination, nothing else. Process discipline pairs with [Superpowers](https://github.com/supportersimulator/superpowers); fleet scale pairs with [Multi-Fleet](https://github.com/supportersimulator/multi-fleet); orchestration pairs with whatever IDE you live in.

We invite you to test it at your scale.

---

## License

MIT — do anything you want, just keep the copyright notice. See [LICENSE](LICENSE).

---

<div align="center">

**Built for engineers who don't ship code reviewed by a single model.**

⭐ Star this repo if you've ever shipped a bug all three would have caught.

</div>
