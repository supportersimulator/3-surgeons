# 3-Surgeons

Multi-model consensus system for Claude Code. Three LLMs cross-examine each other to catch blind spots on critical decisions.

## Why

Claude may confabulate confidently where GPT hedges. A local model catches patterns that API models miss due to token limits. **The value is in the disagreements, not the agreements.**

| Surgeon | Role | Default Model |
|---------|------|---------------|
| **Atlas** (Head Surgeon) | Synthesizes, decides, implements | Claude (this session) |
| **Cardiologist** | External perspective, cross-examination | GPT-4.1-mini (OpenAI) |
| **Neurologist** | Pattern recognition, corrigibility checks | Qwen3-4B (Ollama) |

## Install

### Claude Code

```bash
claude plugin add supportersimulator/3-surgeons
```

### Cursor

```bash
cursor plugin add supportersimulator/3-surgeons
```

### Manual

```bash
git clone https://github.com/supportersimulator/3-surgeons.git ~/.claude/plugins/3-surgeons
cd ~/.claude/plugins/3-surgeons
python -m venv .venv && .venv/bin/pip install -e .
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

## Contributing

1. Fork the repo
2. Create a feature branch
3. Run tests: `python -m pytest tests/ -v`
4. Submit a PR

## License

MIT -- see [LICENSE](LICENSE)
