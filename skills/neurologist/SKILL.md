---
name: neurologist
description: Use for system health pulse checks, corrigibility challenges on proposed actions, and surgeon capability introspection — the local intelligence layer
---

# Neurologist

The Neurologist (Qwen3-4B local) provides three capabilities: health monitoring, corrigibility skepticism, and self-introspection.

## Pulse (Health Check)

Run before critical operations to verify the entire system is healthy.

**When to pulse:**
- Session start (part of probe)
- Before operations that depend on all surgeons being available
- After infrastructure changes (model swaps, endpoint changes)
- When something feels off (slow responses, unexpected results)

**What it checks:**
- `llm_health` — can the neurologist respond?
- `state_backend` — is the state store operational?
- `evidence_store` — is the evidence database accessible?
- `gpu_lock` — is the GPU lock stale (dead PID holding it)?

**MCP tool:** `neurologist_pulse_tool`
**CLI:** `3s neurologist-pulse`

## Challenge (Corrigibility Skeptic)

The neurologist challenges assumptions about proposed changes. Use this before committing to an approach.

**When to challenge:**
- Major architectural decisions
- Changes that affect safety or security
- When you're confident but haven't tested the counter-position
- Before implementing an approach that bypasses existing patterns

**What you get back:**
- `claim` — what was assumed to be true
- `challenge` — the counter-argument
- `severity` — critical, worth_testing, or informational
- `suggested_test` — how to verify the counter-position

**MCP tool:** `neurologist_challenge_tool`
**CLI:** `3s neurologist-challenge "proposed change"`

## Introspect (Capability Self-Report)

Ask each surgeon to honestly report what they can and cannot do.

**When to introspect:**
- After changing models or endpoints
- When a surgeon gives unexpected results
- To calibrate confidence in surgeon outputs

**MCP tool:** `introspect_tool`
**CLI:** `3s introspect`
