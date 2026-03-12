# Host Setup Guide

## Quick Start

```bash
pip install three-surgeons        # core (skills, CLI)
pip install 'three-surgeons[mcp]' # + MCP server (IDE tools)
3s doctor                         # verify installation
```

## By Platform

### macOS (Homebrew)
```bash
brew install python@3.12
python3.12 -m venv ~/.3surgeons/.venv
~/.3surgeons/.venv/bin/pip install 'three-surgeons[mcp]'
3s doctor --json
```

### macOS (pyenv)
```bash
pyenv install 3.12
pyenv global 3.12
pip install 'three-surgeons[mcp]'
```

### Ubuntu / Debian
```bash
sudo apt install python3.12 python3.12-venv
python3.12 -m venv ~/.3surgeons/.venv
~/.3surgeons/.venv/bin/pip install 'three-surgeons[mcp]'
```

### Windows
```powershell
winget install Python.Python.3.12
python -m venv %USERPROFILE%\.3surgeons\.venv
%USERPROFILE%\.3surgeons\.venv\Scripts\pip install three-surgeons[mcp]
```

## Troubleshooting by Error Code

| Code | Meaning | Fix |
|------|---------|-----|
| `3S-PY-OLD` | Python < 3.10 | Install Python 3.12+ (see above) |
| `3S-PY-NONE` | Python not found | Install Python |
| `3S-MCP-MISS` | mcp package missing | `pip install 'three-surgeons[mcp]'` |
| `3S-MCP-IMP` | mcp import error | Reinstall: `pip install --force-reinstall 'three-surgeons[mcp]'` |
| `3S-CFG-DEF` | No config file | Run `3s init` |
| `3S-CFG-ERR` | Config parse error | Check YAML syntax in `~/.3surgeons/config.yaml` |
| `3S-NET-DOWN` | Endpoint unreachable | Check surgeon endpoint URL and network |
| `3S-NET-TMO` | Endpoint timeout | Increase timeout or check server load |
| `3S-KEY-MISS` | API key not set | Set env var (e.g., `OPENAI_API_KEY`) |
| `3S-LOC-NONE` | No local LLM | Start Ollama, LM Studio, or mlx_lm.server |

## IDE Integration

### Claude Code
```bash
cd your-project
claude plugin add 3-surgeons   # auto-discovers MCP server
```

### VS Code
1. Install `context-dna` extension
2. Extension auto-discovers 3-surgeons MCP if installed
3. Run `3s doctor` if tools don't appear

### Cursor
```
cursor plugin add 3-surgeons
```
