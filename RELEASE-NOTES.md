# Release Notes

## 1.0.0 (2026-03-05)

First public release.

### Features
- Multi-model consensus system with 3 LLM "surgeons" (Atlas/Claude, Cardiologist/API, Neurologist/Local)
- 13 skills, 6 commands, MCP server integration
- 3 config presets: hybrid, api-only, local-only
- Provider-agnostic: any OpenAI-compatible endpoint (DeepSeek, Groq, Grok, Mistral, Ollama, LM Studio, vLLM)
- SQLite default state backend (zero external dependencies)
- Evidence store with FTS5 search for institutional memory
- Cost tracking with daily budget enforcement
- 20-vector complexity sentinel
- A/B testing framework with safety rails
- Cross-platform: Claude Code + Cursor support, polyglot Windows/Unix hooks

### Security
- All API keys via environment variables only
- Comprehensive .gitignore for secrets, configs, databases
- No hardcoded credentials anywhere in codebase
