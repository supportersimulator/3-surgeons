# 3-Surgeons for Gemini

Three AI surgeons. One operating table. Your code doesn't ship until all three agree.

## Setup

### 1. Install the extension

```bash
gemini extensions install https://github.com/supportersimulator/3-surgeons
```

### 2. Install Python runtime

Python 3.10+ is required. The MCP server auto-bootstraps on first launch, but you can install manually:

```bash
cd ~/.gemini/extensions/3-surgeons   # or wherever Gemini places extensions
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp]'
```

### 3. Configure surgeon backends

Copy a preset to your home config:

```bash
# Hybrid (default) — OpenAI cardiologist + local Ollama neurologist
cp config/presets/hybrid.yaml ~/.3surgeons/config.yaml

# API-only — OpenAI + DeepSeek, no local model needed
cp config/presets/api-only.yaml ~/.3surgeons/config.yaml

# Local-only — all Ollama, $0 cost, fully private
cp config/presets/local-only.yaml ~/.3surgeons/config.yaml
```

### 4. Set API keys (if using API-backed surgeons)

```bash
# For hybrid or API-only mode
export OPENAI_API_KEY="sk-..."

# For API-only mode (DeepSeek neurologist)
export DEEPSEEK_API_KEY="sk-..."
```

Add these to your shell profile (`~/.zshrc`, `~/.bashrc`) so they persist across sessions.

### 5. Verify

In Gemini, run the probe tool to confirm all three surgeons are reachable:

```
Use the probe tool to check surgeon connectivity
```

Expected: all three surgeons report OK with model names and response times.

## Alternative: Manual MCP configuration

If the extension install does not wire MCP automatically, add this to your Gemini settings (`~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "3-surgeons": {
      "command": "/ABSOLUTE/PATH/TO/3-surgeons/bin/3surgeons-mcp",
      "args": []
    }
  }
}
```

Replace `/ABSOLUTE/PATH/TO/3-surgeons` with the actual path where you cloned the repo.

## Available tools

Once connected, these MCP tools are available in Gemini:

| Tool | What it does |
|------|-------------|
| `probe` | Verify all three surgeons are reachable |
| `cross_examine_start` | Begin a 3-phase cross-examination on a claim |
| `cross_examine_deepen` | Phase 2: surgeons challenge each other's findings |
| `cross_examine_synthesize` | Phase 3: final synthesis with confidence scores |
| `consensus` | Quick confidence-weighted vote from multiple surgeons |
| `sentinel_run` | Scan for complexity risks across configurable dimensions |
| `ask_local_tool` | Query the local neurologist directly |
| `ask_remote_tool` | Query the remote cardiologist directly |
| `research_tool` | Self-directed multi-surgeon research on a topic |
| `cardio_review_tool` | External-model cross-examination review |
| `neurologist_pulse_tool` | Local model health check |
| `neurologist_challenge_tool` | Corrigibility challenge from the neurologist |
| `introspect_tool` | Surgeon capability introspection |
| `gains_gate` | System health and safety invariant checks |
| `ab_propose` | Propose an A/B test |
| `ab_start` | Start a proposed A/B test |
| `ab_measure` | Measure A/B test results |
| `ab_conclude` | Conclude an A/B test with surgeon consensus |

## Troubleshooting

**Tools not appearing**
- Confirm the MCP server is running: `bin/3surgeons-mcp` should start without errors
- Check Python version: `python3 --version` (needs 3.10+)
- Verify installation: `python3 -c "import three_surgeons; print('OK')"`

**Surgeon unreachable**
- Run `probe` to see which surgeon is down
- For local models: ensure Ollama is running (`ollama serve`)
- For API models: verify API key is set in environment

**Auto-bootstrap failed**
- Install manually: `cd /path/to/3-surgeons && python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'`

## More information

- [Full documentation](https://github.com/supportersimulator/3-surgeons)
- [Configuration presets](https://github.com/supportersimulator/3-surgeons/tree/main/config/presets)
- [Skill reference](https://github.com/supportersimulator/3-surgeons/tree/main/skills)
