# 3-Surgeons

Multi-model consensus system for Claude Code. Three LLMs cross-examine each other to catch blind spots on critical decisions.

## Why

Claude may confabulate confidently where GPT hedges. A local model catches patterns that API models miss due to token limits. **The value is in the disagreements, not the agreements.**

| Surgeon | Role | Default Model |
|---------|------|---------------|
| **Atlas** (Head Surgeon) | Synthesizes, decides, implements | Claude (this session) |
| **Cardiologist** | External perspective, cross-examination | GPT-4.1-mini (OpenAI) |
| **Neurologist** | Pattern recognition, corrigibility checks | Qwen3-4B (Ollama) |

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

## Install

### Claude Code (Marketplace)

```bash
# Add the marketplace, then install
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

### Manual (any IDE)

```bash
git clone https://github.com/supportersimulator/3-surgeons.git ~/.claude/plugins/3-surgeons
cd ~/.claude/plugins/3-surgeons
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
```

## Quick Start

```bash
# 1. Run the setup wizard (picks a preset, writes config)
3s init

# 2. Set your API key(s) — see .env.example for all options
export OPENAI_API_KEY=sk-...

# 3. Verify all surgeons are reachable
3s probe

# 4. Cross-examine a decision
3s cross-exam "Should we use Redis or PostgreSQL for session storage?"
```

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

## Configuration

Config lives in `~/.3surgeons/config.yaml` (user-level) or `.3surgeons.yaml` (project-level).

Run `3s init` for guided setup, or copy a preset from `config/presets/`.

See `config/3surgeons.example.yaml` for the full schema.

## Security

- **All API keys are loaded from environment variables** -- never hardcoded, never committed
- `.gitignore` excludes all secret files, config files, and databases
- See `.env.example` for the full list of supported environment variables

## ContextDNA IDE Upgrade

3-Surgeons works standalone. When you're ready for priority queue GPU scheduling, Redis state, and the full butler subconscious, the upgrade is one line:

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

MIT -- see [LICENSE](LICENSE)
