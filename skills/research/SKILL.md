---
name: research
description: Self-directed research on a topic — finds information, synthesizes findings, and tracks costs
---

# Research

GPT-4.1-mini self-directed research with cost tracking. The cardiologist investigates a topic and returns structured findings.

## When to Use

- Exploring an unfamiliar technology or pattern before implementing
- Investigating a bug that requires broader context
- Researching best practices before an architectural decision
- When you need information beyond what's in the codebase

## How It Works

1. You provide a research topic
2. Cardiologist conducts self-directed investigation
3. Returns structured findings with sources
4. Cost tracked against daily budget ($5.00/day default)

## Output

- `findings` — list of discovered facts/insights
- `sources` — where the information came from
- `cost_usd` — how much this research cost

**MCP tool:** `research_tool`
**CLI:** `3s research "topic to investigate"`

## Budget

Research costs are tracked against the daily external budget (default $5.00). The BudgetTracker prevents overspending. If you're near the limit, the cardiologist will note it.

## Cost

~$0.001-0.005 per research query, depending on topic complexity.
