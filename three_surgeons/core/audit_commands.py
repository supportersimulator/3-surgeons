"""Audit and research commands.

Single-LLM: research-evidence
Multi-LLM: cardio-reverify, deep-audit
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)

logger = logging.getLogger(__name__)

# ── Requirements ──────────────────────────────────────────────────────

RESEARCH_EVIDENCE_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    recommended_llms=2,
)

CARDIO_REVERIFY_REQS = CommandRequirements(
    min_llms=2,
    needs_state=True,
    needs_evidence=True,
    needs_git=True,
    recommended_llms=3,
)

DEEP_AUDIT_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    needs_git=True,
    recommended_llms=3,
)


# ── Commands ──────────────────────────────────────────────────────────

def cmd_research_evidence(ctx: RuntimeContext, topic: str) -> CommandResult:
    """Cross-check evidence store for a topic with LLM analysis."""
    # Gather evidence
    evidence_items = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(topic, limit=20)
        except Exception as exc:
            logger.warning("Evidence search failed: %s", exc)

    # LLM cross-examination of evidence
    analysis = "No LLM available for analysis"
    cost_usd = 0.0
    if ctx.healthy_llms and evidence_items:
        llm = ctx.healthy_llms[0]
        evidence_text = "\n".join(
            f"- {item.get('observation', item.get('content', str(item)))}"
            for item in evidence_items[:15]
        )
        try:
            resp = llm.query(
                system=(
                    "You are a research analyst. Cross-check the evidence below. "
                    "Identify patterns, contradictions, and confidence level."
                ),
                prompt=f"Topic: {topic}\n\nEvidence:\n{evidence_text}",
                max_tokens=768,
                temperature=0.3,
            )
            if resp.ok:
                analysis = resp.content
                cost_usd = resp.cost_usd
        except Exception as exc:
            logger.warning("LLM evidence analysis failed: %s", exc)
            analysis = f"LLM analysis failed: {exc}"

    degradation_notes = []
    if len(ctx.healthy_llms) < 2:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"(2 recommended for cross-validation)."
        )

    return CommandResult(
        success=True,
        data={
            "topic": topic,
            "evidence_count": len(evidence_items),
            "analysis": analysis,
            "cost_usd": cost_usd,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )


def _get_recent_git_files(git_root: str, days: int = 7, limit: int = 20) -> List[str]:
    """Get recently changed files from git log."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--name-only",
             "--pretty=format:", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10, cwd=git_root,
        )
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            seen = set()
            unique = []
            for f in files:
                if f not in seen:
                    seen.add(f)
                    unique.append(f)
            return unique[:limit]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def cmd_cardio_reverify(ctx: RuntimeContext, topic: str) -> CommandResult:
    """Multi-surgeon reverification of evidence against current codebase."""
    # Gather evidence
    evidence_items = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(topic, limit=20)
        except Exception:
            pass

    # Get recent git changes for context
    recent_files = []
    if ctx.git_root:
        recent_files = _get_recent_git_files(ctx.git_root)

    # Each surgeon assesses independently
    assessments = []
    total_cost = 0.0
    evidence_text = "\n".join(
        f"- [{item.get('grade', '?')}] {item.get('observation', str(item))}"
        for item in evidence_items[:15]
    )
    file_context = "\n".join(f"- {f}" for f in recent_files[:10]) if recent_files else "No recent changes"

    system_prompt = (
        "You are a surgeon reverifying evidence against current codebase state. "
        "Check if the evidence still holds given recent code changes. "
        "Flag any evidence that may be stale or contradicted by new code."
    )
    user_prompt = (
        f"Topic: {topic}\n\n"
        f"Evidence ({len(evidence_items)} items):\n{evidence_text}\n\n"
        f"Recent code changes:\n{file_context}"
    )

    for i, llm in enumerate(ctx.healthy_llms):
        try:
            resp = llm.query(
                system=system_prompt,
                prompt=user_prompt,
                max_tokens=768,
                temperature=0.3,
            )
            if resp.ok:
                assessments.append({
                    "surgeon_index": i,
                    "model": getattr(resp, "model", "unknown"),
                    "content": resp.content,
                    "cost_usd": resp.cost_usd,
                })
                total_cost += resp.cost_usd
        except Exception as exc:
            logger.warning("Surgeon %d failed during reverify: %s", i, exc)

    degradation_notes = []
    if len(ctx.healthy_llms) < 3:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"(3 recommended for full cross-examination)."
        )

    return CommandResult(
        success=True,
        data={
            "topic": topic,
            "evidence_count": len(evidence_items),
            "assessments": assessments,
            "recent_files_checked": len(recent_files),
            "total_cost_usd": total_cost,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )


def _build_doc_index(git_root: str) -> List[Dict[str, Any]]:
    """Build index of all markdown files with metadata."""
    from pathlib import Path
    import glob

    root = Path(git_root)
    skip_dirs = {
        "node_modules", ".git", ".venv", "venv", "__pycache__", ".tox",
        "bundles", "build", "dist", ".next", ".cache", ".worktrees",
    }
    docs = []
    for md_path in sorted(glob.glob(str(root / "**/*.md"), recursive=True)):
        p = Path(md_path)
        if any(part in skip_dirs for part in p.parts):
            continue
        rel = p.relative_to(root)
        try:
            size = p.stat().st_size
            with open(p, "r", errors="replace") as f:
                lines = f.readlines()
            title = ""
            for line in lines[:10]:
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break
                elif stripped and not title:
                    title = stripped[:80]
            docs.append({
                "path": str(rel),
                "size": size,
                "lines": len(lines),
                "title": title[:100],
            })
        except Exception:
            continue
    return docs


def _read_files(
    git_root: str,
    file_paths: List[str],
    max_chars_per_file: int = 8000,
    max_total_chars: int = 60000,
) -> Dict[str, str]:
    """Read file contents with budget-aware truncation."""
    from pathlib import Path

    root = Path(git_root)
    contents: Dict[str, str] = {}
    total_chars = 0
    for fp in file_paths:
        full = root / fp
        if not full.exists():
            logger.warning("File not found: %s", fp)
            continue
        try:
            with open(full, "r", errors="replace") as f:
                content = f.read()
            if len(content) > max_chars_per_file:
                content = (
                    content[:max_chars_per_file]
                    + f"\n\n[... TRUNCATED at {max_chars_per_file} chars"
                    f" — full file is {len(content)} chars]"
                )
            contents[fp] = content
            total_chars += len(content)
            if total_chars > max_total_chars:
                logger.info("Reached %d char cap — skipping remaining files", total_chars)
                break
        except Exception as exc:
            logger.warning("Error reading %s: %s", fp, exc)
    return contents


def _extract_json(raw: str) -> Any:
    """Extract JSON from LLM output, stripping markdown fences."""
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`")
    return json.loads(raw)


def cmd_deep_audit(
    ctx: RuntimeContext,
    topic: str,
    file_paths: Optional[List[str]] = None,
) -> CommandResult:
    """5-phase chained deep audit pipeline — most comprehensive analysis.

    Phase 1: Document discovery (LLM selects files from doc index, or uses explicit paths)
    Phase 2: Read documents (with budget-aware truncation)
    Phase 3: Feature extraction (structured JSON with status/category/priority)
    Phase 4: Evidence cross-check (BUILT/NOT_BUILT/PARTIALLY_BUILT verdicts)
    Phase 5: Results (gap analysis + A/B test candidates + summary)

    Accepts topic string or explicit file_paths list. Each phase's output
    feeds the next — this is the "chained" architecture.
    """
    phases: Dict[str, Any] = {}
    total_cost = 0.0
    degradation_notes: List[str] = []
    git_root = ctx.git_root or "."

    # ── Phase 1: Document Discovery ──────────────────────────────────
    if file_paths:
        selected = file_paths
        topic_for_prompts = (
            "Deep audit of: " + ", ".join(
                f.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in file_paths[:5]
            )
        )
        phases["discovery"] = {
            "method": "explicit",
            "files_selected": len(selected),
            "files": selected,
        }
    else:
        doc_index = _build_doc_index(git_root)
        topic_for_prompts = topic

        if not ctx.healthy_llms:
            # Fallback: use git log for file selection
            selected = _get_recent_git_files(git_root, days=14, limit=15)
            selected = [f for f in selected if f.endswith(".md")][:10]
            phases["discovery"] = {
                "method": "git_fallback",
                "index_size": len(doc_index),
                "files_selected": len(selected),
                "files": selected,
            }
            degradation_notes.append(
                "No LLM available for intelligent file selection — "
                "using recent git changes as fallback."
            )
        else:
            # LLM selects files from doc index
            from collections import defaultdict
            by_dir: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for d in doc_index:
                top = d["path"].split("/")[0] if "/" in d["path"] else "root"
                by_dir[top].append(d)

            index_text = f"# Document Index — {len(doc_index)} markdown files\n\n"
            for dir_name, dir_docs in sorted(by_dir.items()):
                index_text += f"\n## {dir_name}/ ({len(dir_docs)} files)\n"
                for d in dir_docs:
                    index_text += f"- [{d['lines']:4d}L {d['size']:6d}B] {d['path']}"
                    if d["title"]:
                        index_text += f" — {d['title']}"
                    index_text += "\n"

            resp = ctx.healthy_llms[0].query(
                system=(
                    "You are running a DEEP AUDIT — finding planned-but-unbuilt features.\n\n"
                    "Select 5-10 files most likely to contain:\n"
                    "- Feature plans, design docs, implementation roadmaps\n"
                    "- Architecture decisions with TODO/future items\n"
                    "- Dependency audits with recommended fixes\n\n"
                    "Prefer files with more content (higher line count).\n"
                    "RESPOND ONLY as a JSON array of file paths."
                ),
                prompt=(
                    f"AUDIT TOPIC: {topic}\n\n"
                    f"{index_text}\n\n"
                    "Select 5-10 files for deep audit. JSON array only."
                ),
                max_tokens=1024,
                temperature=0.3,
            )
            total_cost += resp.cost_usd

            if resp.ok:
                try:
                    selected = _extract_json(resp.content)
                    if not isinstance(selected, list):
                        selected = [selected]
                except (json.JSONDecodeError, IndexError):
                    logger.warning("Could not parse file selection, falling back to git")
                    selected = [
                        f for f in _get_recent_git_files(git_root, days=14, limit=15)
                        if f.endswith(".md")
                    ][:10]
            else:
                selected = [
                    f for f in _get_recent_git_files(git_root, days=14, limit=15)
                    if f.endswith(".md")
                ][:10]

            phases["discovery"] = {
                "method": "llm_selected",
                "index_size": len(doc_index),
                "files_selected": len(selected),
                "files": selected,
                "selection_cost_usd": resp.cost_usd,
            }

    if not selected:
        return CommandResult(
            success=False,
            data={"topic": topic, "phases": phases, "error": "No files found for audit"},
            blocked=True,
            blocked_reason="No documents found to audit.",
        )

    # ── Phase 2: Read Documents ──────────────────────────────────────
    file_contents = _read_files(git_root, selected)
    phases["documents"] = {
        "files_read": len(file_contents),
        "total_chars": sum(len(c) for c in file_contents.values()),
        "files": list(file_contents.keys()),
    }

    if not file_contents:
        return CommandResult(
            success=False,
            data={"topic": topic, "phases": phases, "error": "No files could be read"},
            blocked=True,
            blocked_reason="No files could be read — aborting.",
        )

    # ── Phase 3: Feature Extraction (chained — uses Phase 2 output) ──
    docs_text = ""
    for fp, content in file_contents.items():
        docs_text += f"\n{'=' * 60}\n## FILE: {fp}\n{'=' * 60}\n{content}\n"

    planned_items: List[Dict[str, Any]] = []
    discovery_summary = ""

    if ctx.healthy_llms:
        resp = ctx.healthy_llms[0].query(
            system=(
                "You are conducting a DEEP AUDIT.\n"
                "Extract every planned feature, recommended fix, and TODO item "
                "from these documents.\n\n"
                "For each item, classify its implementation status:\n"
                "- PLANNED: Described in detail but marked as future/next/TODO\n"
                "- RECOMMENDED: An audit/review recommended this but no implementation mentioned\n"
                "- PARTIAL: Some work described but not complete\n"
                "- UNKNOWN: Can't determine status from documents alone\n\n"
                "Output as JSON:\n"
                "{\n"
                '  "planned_items": [\n'
                '    {\n'
                '      "name": "Short descriptive name",\n'
                '      "description": "What this feature/fix does (1-2 sentences)",\n'
                '      "source_file": "path/to/file.md",\n'
                '      "status": "PLANNED|RECOMMENDED|PARTIAL|UNKNOWN",\n'
                '      "category": "feature|fix|infrastructure|security|performance|testing",\n'
                '      "priority": "critical|high|medium|low",\n'
                '      "implementation_hints": "Files/modules mentioned, approach described"\n'
                '    }\n'
                '  ],\n'
                '  "total_items": N,\n'
                '  "summary": "High-level summary of what these docs plan"\n'
                "}"
            ),
            prompt=(
                f"AUDIT TOPIC: {topic_for_prompts}\n\n"
                f"=== DOCUMENTS ({len(file_contents)} files) ===\n{docs_text}\n\n"
                "Extract ALL planned features, recommended fixes, and TODO items. JSON only."
            ),
            max_tokens=4096,
            temperature=0.3,
        )
        total_cost += resp.cost_usd

        if resp.ok:
            try:
                parsed = _extract_json(resp.content)
                planned_items = parsed.get("planned_items", [])
                discovery_summary = parsed.get("summary", "")
            except (json.JSONDecodeError, IndexError) as exc:
                logger.warning("Could not parse feature extraction: %s", exc)
                degradation_notes.append(f"Feature extraction JSON parse failed: {exc}")
    else:
        degradation_notes.append("No LLM available for feature extraction.")

    phases["extraction"] = {
        "planned_items": planned_items,
        "item_count": len(planned_items),
        "summary": discovery_summary,
        "extraction_cost_usd": resp.cost_usd if ctx.healthy_llms else 0,
    }

    # ── Phase 4: Evidence Cross-Check (chained — uses Phase 3 output) ─
    evidence_items: List[Dict[str, Any]] = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(topic, limit=30)
        except Exception:
            pass

    evidence_text = "\n".join(
        f"- {item.get('title', '')}: {item.get('content', item.get('observation', str(item)))}"
        for item in evidence_items[:20]
    )

    gap_analysis: List[Dict[str, Any]] = []
    ab_candidates: List[Dict[str, Any]] = []
    audit_summary: Dict[str, Any] = {}

    if ctx.healthy_llms and (planned_items or evidence_items):
        planned_text = (
            json.dumps(planned_items, indent=2)
            if planned_items
            else discovery_summary or "No structured items extracted"
        )

        resp = ctx.healthy_llms[0].query(
            system=(
                "You are conducting the CROSS-CHECK phase of a Deep Audit.\n\n"
                "You have:\n"
                "1. A list of planned features/fixes extracted from project documents\n"
                "2. Evidence from the project's evidence store (learnings, claims)\n\n"
                "For each planned item, determine if it was ACTUALLY BUILT.\n"
                "Cross-reference the evidence store for implementation signals:\n"
                "- Success records mentioning the feature\n"
                "- Bug fixes related to the feature (implies it exists)\n"
                "- Claims about its status\n\n"
                "Output as JSON:\n"
                "{\n"
                '  "gap_analysis": [\n'
                '    {\n'
                '      "name": "Feature name (from planned items)",\n'
                '      "verdict": "BUILT|NOT_BUILT|PARTIALLY_BUILT|SUPERSEDED|UNCERTAIN",\n'
                '      "evidence": "What evidence supports this verdict",\n'
                '      "confidence": 0.0,\n'
                '      "priority": "critical|high|medium|low",\n'
                '      "recommendation": "What to do about this gap (if NOT_BUILT/PARTIALLY_BUILT)"\n'
                '    }\n'
                '  ],\n'
                '  "ab_test_candidates": [\n'
                '    {\n'
                '      "name": "Feature/approach worth A/B testing",\n'
                '      "hypothesis": "Why testing this would be valuable",\n'
                '      "control": "Current approach (status quo)",\n'
                '      "variant": "Alternative to test",\n'
                '      "success_metric": "How to measure which is better",\n'
                '      "effort": "low|medium|high",\n'
                '      "priority": 1\n'
                '    }\n'
                '  ],\n'
                '  "summary": {\n'
                '    "total_planned": 0,\n'
                '    "built": 0,\n'
                '    "not_built": 0,\n'
                '    "partially_built": 0,\n'
                '    "uncertain": 0,\n'
                '    "narrative": "2-3 sentence overall assessment"\n'
                '  }\n'
                "}"
            ),
            prompt=(
                f"AUDIT TOPIC: {topic_for_prompts}\n\n"
                f"=== PLANNED ITEMS ({len(planned_items)} items) ===\n{planned_text}\n\n"
                f"=== EVIDENCE FROM STORE ({len(evidence_items)} items) ===\n"
                f"{evidence_text}\n\n"
                "Cross-check each planned item against the evidence. "
                "Which were built? Which are gaps? JSON only."
            ),
            max_tokens=4096,
            temperature=0.3,
        )
        total_cost += resp.cost_usd

        if resp.ok:
            try:
                parsed_cc = _extract_json(resp.content)
                gap_analysis = parsed_cc.get("gap_analysis", [])
                ab_candidates = parsed_cc.get("ab_test_candidates", [])
                audit_summary = parsed_cc.get("summary", {})
            except (json.JSONDecodeError, IndexError) as exc:
                logger.warning("Could not parse cross-check output: %s", exc)
                degradation_notes.append(f"Cross-check JSON parse failed: {exc}")
    else:
        if not ctx.healthy_llms:
            degradation_notes.append("No LLM available for evidence cross-check.")

    phases["cross_check"] = {
        "evidence_count": len(evidence_items),
        "gap_analysis": gap_analysis,
        "ab_test_candidates": ab_candidates,
        "cross_check_cost_usd": resp.cost_usd if ctx.healthy_llms and (planned_items or evidence_items) else 0,
    }

    # ── Phase 5: Results ─────────────────────────────────────────────
    if len(ctx.healthy_llms) < 3:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) (3 recommended)."
        )

    return CommandResult(
        success=True,
        data={
            "topic": topic,
            "phases": phases,
            "gap_analysis": gap_analysis,
            "ab_test_candidates": ab_candidates,
            "summary": audit_summary,
            "total_cost_usd": total_cost,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )
