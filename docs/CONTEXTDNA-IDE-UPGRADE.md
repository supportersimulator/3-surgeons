# Upgrading to ContextDNA IDE

3-Surgeons is the open-source foundation. ContextDNA IDE adds priority queue GPU scheduling, Redis-backed state, persistent evidence, and the full butler subconscious. The upgrade is designed for near-zero friction.

## Architecture: 3 Layers

```
Layer 0: 3-Surgeons (open source, pure protocol)
  - Raw HTTP to OpenAI-compatible endpoints
  - SQLite state backend
  - Local evidence store
  - All cross-exam, consensus, sentinel features work standalone

Layer 1: Swap endpoints (minimal config change)
  - Point surgeons at ContextDNA-managed LLM endpoints
  - Same config.yaml, same commands, same protocol

Layer 2: Full ContextDNA IDE (one-line adapter injection)
  - Priority queue GPU scheduling (prevents local LLM stampeding)
  - Redis-backed state with sorted sets and hashes
  - Persistent evidence store with PostgreSQL
  - 9-section webhook injection (professor wisdom, gotchas, Synaptic)
  - Gold mining, session historian, anticipation engine
```

## The QueryAdapter Seam

The entire upgrade pivots on one parameter: `query_adapter` on `LLMProvider`.

### Open-source (zero dependencies)

```python
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.config import SurgeonConfig

config = SurgeonConfig(
    provider="ollama",
    endpoint="http://localhost:11434/v1",
    model="qwen3:4b",
    api_key_env="",
    role="neurologist",
)
provider = LLMProvider(config)  # Raw HTTP, no adapter
```

### ContextDNA IDE (one-line upgrade)

```python
from three_surgeons.core.models import LLMProvider
from contextdna.adapters import priority_queue_adapter

provider = LLMProvider(config, query_adapter=priority_queue_adapter)
```

Same protocol, same evidence store, same cross-exam -- just smarter routing.

## What the Adapter Does

The `QueryAdapter` protocol signature:

```python
def __call__(
    self,
    system: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> LLMResponse
```

The ContextDNA `priority_queue_adapter` implementation:
- Routes through `llm_priority_queue.py` instead of raw HTTP
- Acquires Redis GPU lock before Metal operations (prevents stampeding on shared GPU)
- Respects 4-tier priority: P1 AARON > P2 ATLAS > P3 EXTERNAL > P4 BACKGROUND
- Urgent flag: P1/P2 callers set `llm:gpu_urgent` so P4 holders yield after current request
- External fallback: on local failure, P1/P2 route to GPT-4.1-mini automatically
- Cost tracking: all calls logged to `llm:costs:{date}` in Redis

## What Stays the Same

These components work identically in both modes:

| Component | Open Source | ContextDNA IDE |
|-----------|-----------|----------------|
| Cross-examination protocol | Same | Same |
| Evidence grading ladder | Same (SQLite) | Same (PostgreSQL) |
| Consensus voting | Same | Same |
| Sentinel complexity vectors | Same | Same |
| Corrigibility gate | Same | Same |
| Gains gate checks | Same | Same + Redis checks |
| Config format | `config.yaml` | `config.yaml` + env overrides |

## What Changes

| Feature | Open Source | ContextDNA IDE |
|---------|-----------|----------------|
| LLM routing | Raw HTTP | Priority queue with GPU lock |
| State backend | SQLite | Redis sorted sets + hashes |
| Evidence persistence | Local SQLite | PostgreSQL with replication |
| Webhook injection | None | 9-section subconscious |
| Session memory | None | Gold mining + session historian |
| Cost tracking | Per-call estimate | Aggregated daily budgets |
| Multi-machine | Not supported | Branch ownership + coordination |

## Migration Checklist

When upgrading a project from 3-Surgeons to ContextDNA IDE:

1. **Install ContextDNA IDE** (separate package, includes 3-Surgeons as dependency)
2. **Import the adapter**: `from contextdna.adapters import priority_queue_adapter`
3. **Pass adapter to providers**: `LLMProvider(config, query_adapter=priority_queue_adapter)`
4. **Migrate state** (optional): `contextdna migrate-state --from sqlite --to redis`
5. **Migrate evidence** (optional): `contextdna migrate-evidence --from sqlite --to postgres`
6. **Verify**: `3s probe` -- all surgeons should report healthy through the new routing

Steps 4-5 are optional because 3-Surgeons continues to work with SQLite. The IDE adds Redis/PostgreSQL as higher-performance backends but doesn't require immediate migration.

## Writing Adapter-Compatible Code

When contributing to 3-Surgeons, keep the adapter seam clean:

- All LLM calls go through `LLMProvider.query()` -- never raw HTTP in feature code
- Use `LLMResponse` dataclass for all return types -- adapters return this too
- Don't assume HTTP-specific behavior (status codes, headers) in callers
- Think-tag stripping is handled inside `LLMProvider` -- callers get clean content
- Cost estimation works for both paths (adapter may override with actual costs)
