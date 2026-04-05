# 3-Surgeons on Codex

Setup guide for using 3-Surgeons with [Codex CLI](https://github.com/openai/codex) and the Codex IDE extension. Both surfaces share the same MCP configuration.

## Install

```bash
# 1. Clone the repo
git clone https://github.com/supportersimulator/3-surgeons.git ~/.3surgeons/plugin

# 2. Create venv and install
cd ~/.3surgeons/plugin
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp]'

# 3. Set your API key (add to shell profile for persistence)
export OPENAI_API_KEY=sk-...
```

## Register the MCP Server

**Option A: CLI registration (quickest)**

```bash
codex mcp add 3-surgeons -- ~/.3surgeons/plugin/bin/3surgeons-mcp
```

**Option B: Global config file**

Add to `~/.codex/config.toml`:

```toml
[mcp_servers."3-surgeons"]
command = "/Users/you/.3surgeons/plugin/bin/3surgeons-mcp"
args = []
```

Replace `/Users/you` with your actual home directory.

**Option C: Project-scoped config**

Copy the example into your project:

```bash
mkdir -p .codex
cp ~/.3surgeons/plugin/.codex/config.toml.example .codex/config.toml
```

Edit paths if needed. This makes 3-Surgeons available only within that project.

## Verify

```bash
# Start Codex and check MCP tools are loaded
codex
/mcp
```

You should see the 3-Surgeons tools listed (probe, cross_examine, consensus, sentinel, etc.).

From the CLI outside Codex:

```bash
cd ~/.3surgeons/plugin
3s probe
```

All three surgeons should report reachable.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (hybrid/API mode) | OpenAI key for Cardiologist (GPT-4.1-mini) |
| `OLLAMA_HOST` | No | Ollama endpoint for local Neurologist (default: `http://127.0.0.1:11434`) |
| `DEEPSEEK_API_KEY` | No | DeepSeek key for API-Only mode Neurologist |

Set these in your shell profile (`~/.zshrc`, `~/.bashrc`) or pass via Codex:

```bash
codex mcp add 3-surgeons --env OPENAI_API_KEY=sk-... -- ~/.3surgeons/plugin/bin/3surgeons-mcp
```

## Modes

Works the same as all other IDEs. Pick one:

- **Hybrid** (default) — OpenAI + local Ollama. 1 API key. ~$0.003/query.
- **API-Only** — OpenAI + DeepSeek. 2 API keys. ~$0.005/query.
- **Local-Only** — Ollama only. $0.

Run `3s init` to configure, or copy a preset:

```bash
cp ~/.3surgeons/plugin/config/presets/api-only.yaml ~/.3surgeons/config.yaml
```

## Troubleshooting

**Tools not appearing in `/mcp`**
- Confirm the path in `config.toml` is absolute and correct
- Check Python 3.10+ is installed: `python3 --version`
- Re-run install: `cd ~/.3surgeons/plugin && .venv/bin/pip install -e '.[mcp]'`

**"Cannot find Python >=3.10" error**
- The launcher checks venv, user venv, then system Python
- Ensure `.venv` was created inside the clone: `ls ~/.3surgeons/plugin/.venv/bin/python`

**Surgeon unreachable**
- Run `3s probe` to see which surgeon fails
- Check `OPENAI_API_KEY` is set in the environment Codex runs in
- For local Neurologist: ensure Ollama is running (`ollama serve`)

**Windows**
- The `bin/3surgeons-mcp` launcher is Bash. On Windows, call Python directly:
  ```
  codex mcp add 3-surgeons -- python -m three_surgeons.mcp.server
  ```
  Ensure `three_surgeons` is importable from the Python on your PATH.
