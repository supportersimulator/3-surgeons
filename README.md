# 3-Surgeons

**Three AI surgeons. One operating table. Your code doesn't ship until all three agree.**

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

## Contributing

1. Fork the repo
2. Create a feature branch
3. Run tests: `python -m pytest tests/ -v`
4. Submit a PR

## License

MIT — see [LICENSE](LICENSE)
