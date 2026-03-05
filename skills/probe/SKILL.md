---
name: probe
description: Invoke at session start, before critical operations, or after infrastructure changes to verify all three surgeons are reachable and operational
---

# Probe

## When to Probe

Probe is a health check -- it pings both the Cardiologist and Neurologist endpoints to verify they are reachable and responding. Run it:

- **At session start** -- before relying on any surgeon, confirm they are online
- **Before critical operations** -- if you are about to run a cross-examination or consensus that you cannot afford to have partially fail, probe first
- **After infrastructure changes** -- restarted Ollama, changed API keys, modified config, switched networks
- **When a surgeon returns errors** -- diagnose whether the issue is transient (network blip) or persistent (config error, service down)

**Do NOT use for**: routine operations where partial degradation is acceptable, or as a substitute for gains-gate (probe checks connectivity only, not full system health).

## How to Invoke

### CLI

```bash
3s probe
```

### MCP Tool

```
probe()
```

No arguments needed. Probe checks all configured surgeons.

## Interpreting Results

### CLI Output

```
Probing surgeons...

  Cardiologist: OK (245ms)
  Neurologist: OK (89ms)
  Atlas (Claude): always available (this session)

All surgeons operational.
```

### MCP Tool Output

```json
{
  "cardiologist": {"status": "ok", "latency_ms": 245},
  "neurologist": {"status": "ok", "latency_ms": 89},
  "atlas": {"status": "ok", "note": "always available (this session)"}
}
```

### Status Values

| Status | Meaning |
|--------|---------|
| `ok` | Surgeon responded successfully. `latency_ms` shows response time. |
| `fail` | Surgeon responded but with an error (e.g., invalid API key, model not found). Check the `error` field. |
| `unreachable` | Could not connect to the endpoint at all (network issue, service not running). |

### Atlas Status

Atlas (Claude) is always reported as `ok` because it IS the current session. There is no endpoint to ping -- if you are reading this output, Atlas is operational.

## What to Do When a Surgeon Is Down

### Cardiologist Down (OpenAI API)

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `unreachable` | Network issue, OpenAI outage | Check internet, check [status.openai.com](https://status.openai.com) |
| `fail` with 401 | Invalid API key | Verify `OPENAI_API_KEY` env var is set and valid |
| `fail` with 429 | Rate limited | Wait, reduce request frequency |
| `fail` with 500+ | OpenAI server error | Retry in a few minutes |

**Impact of Cardiologist being down**: Cross-examination runs with Neurologist only. Consensus uses only Neurologist's vote (weighted score less reliable). A/B test proposals still work (local). Cost tracking pauses for external calls.

### Neurologist Down (Local Model)

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `unreachable` | Ollama/MLX not running | Start Ollama: `ollama serve` |
| `unreachable` | Wrong endpoint in config | Check `~/.3surgeons/config.yaml` neurologist endpoint |
| `fail` | Model not pulled | Pull the model: `ollama pull qwen3:4b` |

**Impact of Neurologist being down**: Cross-examination runs with Cardiologist only. Consensus uses only Cardiologist's vote. Local pattern recognition unavailable. All operations still function but with reduced diversity of perspective.

### Both Surgeons Down

If both external surgeons are unreachable, Atlas (Claude) is still operational but without the multi-model consensus benefit. In this state:

1. **Do NOT run cross-examination or consensus** -- results will be empty/meaningless
2. **Fix connectivity first** -- use `3s init` to reconfigure if endpoints changed
3. **Proceed with caution** on critical decisions -- single-model analysis lacks the cross-check safety net

## Probe vs Gains-Gate

| | Probe | Gains-Gate |
|---|-------|------------|
| **Checks** | Surgeon connectivity only | Connectivity + evidence store + state backend + more |
| **Speed** | Fast (~500ms) | Medium (~2-5s) |
| **Use case** | Quick health check | Phase transition verification |
| **Blocks on failure** | No (informational) | Yes (critical checks block progress) |

Use probe for quick checks. Use gains-gate between major phases when you need to verify the full system is healthy.

## Latency Benchmarks

Healthy response times to expect:

| Surgeon | Typical Latency | Concerning |
|---------|----------------|------------|
| Cardiologist (OpenAI) | 200-500ms | >2000ms |
| Neurologist (local Ollama) | 50-200ms | >1000ms |

High latency on the Neurologist usually indicates the local model is loading into memory (first request after start). Subsequent requests should be faster.
