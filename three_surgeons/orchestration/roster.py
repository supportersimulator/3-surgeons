"""Reviewer roster — who can we ask for a second opinion?

Ported from IJFW's ``mcp-server/src/audit-roster.js`` per the harvest plan
(2026-04-25 ContextDNA strategic doc). Adapted for 3-Surgeons:

* IJFW's "auditor" → 3-Surgeons "reviewer".
* IJFW's "Trident" branding dropped — kept the family-diversity *principle*
  without tying it to a brand.
* IJFW-specific CLI flags (e.g. Codex sandbox config) preserved verbatim
  because they reflect real safety hardening that survived audit there.
* The 3-Surgeons lineage (cardiologist/neurologist/atlas) is *not* a
  reviewer — it's the existing consult pipeline. This module supplements
  that for cross-exam / second-opinion scenarios where independent CLI
  reviewers add lineage diversity.

DESIGN
------
* :data:`ROSTER` lists known reviewers with id, family, invoke command,
  env-var fingerprints for self-detection, and optional API fallback.
* :func:`detect_self` figures out which CLI is calling, so we never ask
  the same lineage to review its own output.
* :func:`is_reachable` checks both CLI-on-PATH and API-key-in-env.
* :func:`pick_reviewers` accepts ``priority`` or ``diversity`` strategy.
  Diversity prefers openai-family + google-family for genuine model
  disagreement; backfills from oss when families are missing.

NOT GOALS
---------
* Not a router for the *internal* surgeons (cardio/neuro/atlas) — those
  live in :mod:`three_surgeons.adapters`.
* Not a workflow orchestrator — that's :mod:`three_surgeons.orchestration.cross`
  (next harvest pass: cross-orchestrator).
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiFallback:
    provider: str
    model: str
    auth_env: str
    endpoint: str


@dataclass(frozen=True)
class ReviewerEntry:
    """One row in :data:`ROSTER`."""
    id: str
    family: str  #: "openai" | "google" | "anthropic" | "oss"
    name: str
    invoke: str  #: shell command (first word = binary name to PATH-probe)
    note: str
    env_keys: tuple[str, ...] = ()  #: env vars that prove self-identity
    cmd_keys: tuple[str, ...] = ()  #: substrings of $_  (calling cmd) that prove self-identity
    api_fallback: ApiFallback | None = None


# Roster is a module-level constant. Adding a new reviewer = appending here.
ROSTER: tuple[ReviewerEntry, ...] = (
    ReviewerEntry(
        id="codex",
        family="openai",
        name="Codex CLI",
        invoke=(
            'codex exec --skip-git-repo-check --sandbox read-only '
            '-c approval_policy="never" '
            '-c mcp_servers.three-surgeons.enabled=false -'
        ),
        note=(
            "Different training lineage; fast on review tasks. The - flag "
            "reads prompt from stdin. --skip-git-repo-check bypasses the "
            "trusted-directory gate added in codex-cli 0.118.0. --sandbox "
            "read-only blocks the model from running shell commands on "
            "the host. approval_policy=never auto-approves without "
            "interactive prompt. mcp_servers.three-surgeons.enabled=false "
            "prevents recursion when 3-Surgeons calls Codex which would "
            "otherwise re-enter 3-Surgeons MCP."
        ),
        env_keys=("CODEX_SESSION_ID", "CODEX_HOME"),
        cmd_keys=("codex",),
        api_fallback=ApiFallback(
            provider="openai",
            model="gpt-4o-mini",
            auth_env="OPENAI_API_KEY",
            endpoint="https://api.openai.com/v1/chat/completions",
        ),
    ),
    ReviewerEntry(
        id="gemini",
        family="google",
        name="Gemini CLI",
        invoke="gemini",
        note=(
            "Strong on security + architectural patterns. Auto-detects "
            "piped stdin for headless mode."
        ),
        env_keys=("GEMINI_CLI", "GOOGLE_CLOUD_PROJECT_GEMINI"),
        cmd_keys=("gemini-cli",),
        api_fallback=ApiFallback(
            provider="google",
            model="gemini-2.0-flash",
            auth_env="GEMINI_API_KEY",
            endpoint=(
                "https://generativelanguage.googleapis.com"
                "/v1beta/models/{model}:generateContent"
            ),
        ),
    ),
    ReviewerEntry(
        id="opencode",
        family="oss",
        name="opencode",
        invoke="opencode",
        note="OSS / local-friendly; good when privacy matters.",
        env_keys=("OPENCODE_SESSION", "OPENCODE_HOME"),
    ),
    ReviewerEntry(
        id="aider",
        family="oss",
        name="Aider",
        invoke="aider --message",
        note="Code-focused peer; terse + diff-aware.",
        env_keys=("AIDER_SESSION",),
        cmd_keys=("aider",),
    ),
    ReviewerEntry(
        id="copilot",
        family="openai",
        name="Copilot CLI",
        invoke="gh copilot suggest",
        note="Convenient if gh CLI is already authenticated.",
        env_keys=("GH_COPILOT_TOKEN", "COPILOT_CLI_SESSION"),
    ),
    ReviewerEntry(
        id="claude",
        family="anthropic",
        name="Claude Code",
        invoke="claude -p",
        note=(
            "Anthropic; useful when you want a second Claude pass in a "
            "fresh session."
        ),
        env_keys=("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PLUGIN_ROOT"),
        api_fallback=ApiFallback(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            auth_env="ANTHROPIC_API_KEY",
            endpoint="https://api.anthropic.com/v1/messages",
        ),
    ),
)


# Module-level cache: PATH probe is repeated across many calls; result
# is stable for the lifetime of the process.
_INSTALLED_CACHE: dict[str, bool] = {}


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def detect_self(env: Mapping[str, str] | None = None) -> str | None:
    """Return the id of the current caller, or ``None`` if unknown.

    Conservative: if no fingerprint matches, returns None rather than
    guessing — caller is then NOT filtered out of the roster.
    """
    e = _env(env)
    cmd = str(e.get("_", ""))
    for entry in ROSTER:
        try:
            for key in entry.env_keys:
                if e.get(key):
                    return entry.id
            for needle in entry.cmd_keys:
                if needle.lower() in cmd.lower():
                    return entry.id
        except Exception as exc:  # noqa: BLE001 — never break on detection
            logger.debug("detect_self: %s probe raised: %s", entry.id, exc)
    return None


def is_installed(reviewer_id: str) -> bool:
    """Return True if the reviewer's CLI binary is on PATH (cached)."""
    if reviewer_id in _INSTALLED_CACHE:
        return _INSTALLED_CACHE[reviewer_id]
    entry = next((r for r in ROSTER if r.id == reviewer_id), None)
    if entry is None:
        return False
    binary = entry.invoke.split()[0]
    installed = shutil.which(binary) is not None
    _INSTALLED_CACHE[reviewer_id] = installed
    return installed


def _reset_cache() -> None:
    """Test helper: clear the PATH probe cache."""
    _INSTALLED_CACHE.clear()


@dataclass(frozen=True)
class Reachability:
    cli: bool
    api: bool

    @property
    def any(self) -> bool:
        return self.cli or self.api

    def to_dict(self) -> dict:
        return {"cli": self.cli, "api": self.api, "any": self.any}


def is_reachable(
    reviewer_id: str, env: Mapping[str, str] | None = None,
) -> Reachability:
    """CLI-on-PATH OR API-key-in-env."""
    entry = next((r for r in ROSTER if r.id == reviewer_id), None)
    if entry is None:
        return Reachability(cli=False, api=False)
    cli_ok = is_installed(reviewer_id)
    api_ok = bool(
        entry.api_fallback and _env(env).get(entry.api_fallback.auth_env)
    )
    return Reachability(cli=cli_ok, api=api_ok)


@dataclass(frozen=True)
class ReviewerStatus:
    entry: ReviewerEntry
    is_self: bool
    installed: bool
    reachable: Reachability

    @property
    def id(self) -> str:
        return self.entry.id


def roster_with_status(
    env: Mapping[str, str] | None = None,
) -> list[ReviewerStatus]:
    """Return roster annotated with self/installed/reachable flags."""
    self_id = detect_self(env)
    return [
        ReviewerStatus(
            entry=e,
            is_self=(e.id == self_id),
            installed=is_installed(e.id),
            reachable=is_reachable(e.id, env),
        )
        for e in ROSTER
    ]


@dataclass(frozen=True)
class Pick:
    """A reviewer chosen by :func:`pick_reviewers`. ``preferred_source`` is
    ``"cli"`` when the binary is on PATH, ``"api"`` when only the API key
    is present (fallback path)."""
    entry: ReviewerEntry
    preferred_source: str  # "cli" | "api"

    @property
    def id(self) -> str:
        return self.entry.id


@dataclass(frozen=True)
class Missing:
    family: str
    reason: str


@dataclass(frozen=True)
class PickResult:
    picks: list[Pick] = field(default_factory=list)
    missing: list[Missing] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "picks": [
                {
                    "id": p.id,
                    "family": p.entry.family,
                    "preferred_source": p.preferred_source,
                }
                for p in self.picks
            ],
            "missing": [{"family": m.family, "reason": m.reason} for m in self.missing],
            "note": self.note,
        }


def _annotate(
    status: ReviewerStatus, env: Mapping[str, str] | None = None,
) -> Pick:
    """Return a Pick with preferred_source set based on reachability."""
    reach = status.reachable
    if not reach.cli and reach.api:
        return Pick(entry=status.entry, preferred_source="api")
    return Pick(entry=status.entry, preferred_source="cli")


_TARGET_FAMILIES: tuple[str, ...] = ("openai", "google")


def pick_reviewers(
    *,
    count: int = 2,
    env: Mapping[str, str] | None = None,
    only: str | None = None,
    strategy: str = "priority",
) -> PickResult:
    """Choose ``count`` reviewers, never including the caller's lineage.

    Strategies:

    * ``"priority"`` (default) — top N reachable non-self in ROSTER order.
    * ``"diversity"`` — prefer openai + google families. Backfill from oss
      when a family is missing or coincides with the caller. Diversity
      maximises the chance of catching blind spots that any single
      lineage would share.

    ``only`` filters to a comma/space-separated id list. Always returns
    a populated note when the result is short or empty (positive framing,
    actionable advice).
    """
    e = _env(env)
    all_entries = roster_with_status(e)

    if only:
        ids = [s.lower() for s in only.replace(",", " ").split() if s.strip()]
        wanted = [next((s for s in all_entries if s.id == i), None) for i in ids]
        wanted = [s for s in wanted if s is not None]
        reachable_picks = [_annotate(s, e) for s in wanted if s.reachable.any]
        unreachable = [
            Missing(family=s.entry.family, reason=f"{s.id} not reachable")
            for s in wanted if not s.reachable.any
        ]
        note = (
            "Requested but not reachable: "
            f"{', '.join(m.family for m in unreachable)}."
            if unreachable else ""
        )
        return PickResult(
            picks=reachable_picks, missing=unreachable, note=note,
        )

    if strategy == "diversity":
        return _pick_diversity(all_entries, e)

    # Default: priority strategy
    eligible = [
        s for s in all_entries if not s.is_self and s.reachable.any
    ]
    picks = [_annotate(s, e) for s in eligible[:count]]
    missing = [
        Missing(family=s.entry.family, reason=f"{s.id} not reachable")
        for s in all_entries if not s.is_self and not s.reachable.any
    ]
    note = ""
    if not picks:
        note = (
            "No external reviewers reachable. Install codex, gemini, "
            "opencode, aider, or copilot (or set OPENAI_API_KEY / "
            "GEMINI_API_KEY) to enable cross-review."
        )
    elif len(picks) < count:
        short = count - len(picks)
        ids = ", ".join(p.id for p in picks)
        note = (
            f"Cross-review prefers ≥2 lineages alongside the caller. "
            f"Only {len(picks)} reachable ({ids}); {short} short. "
            "Install another to triangulate findings — single-reviewer "
            "passes miss what overlap would catch."
        )
    return PickResult(picks=picks, missing=missing, note=note)


def _pick_diversity(
    all_entries: list[ReviewerStatus], env: Mapping[str, str],
) -> PickResult:
    self_id = detect_self(env)
    self_entry = next(
        (e for e in ROSTER if e.id == self_id), None,
    )
    caller_family = self_entry.family if self_entry else None

    eligible = [
        s for s in all_entries if not s.is_self and s.reachable.any
    ]

    def by_family(fam: str) -> list[ReviewerStatus]:
        return [s for s in eligible if s.entry.family == fam]

    picks: list[Pick] = []
    picked: set[str] = set()
    missing: list[Missing] = []
    nudges: list[str] = []

    for fam in _TARGET_FAMILIES:
        if fam == caller_family:
            backfill = next(
                (s for s in eligible
                 if s.id not in picked and s.entry.family != caller_family),
                None,
            )
            if backfill is not None:
                picks.append(_annotate(backfill, env))
                picked.add(backfill.id)
                other_fam = "google" if fam == "openai" else "openai"
                nudges.append(
                    f"No {fam}-family reviewer outside caller — using "
                    f"{backfill.id} ({backfill.entry.family}) as stand-in. "
                    f"Install a {other_fam}-family reviewer for full "
                    "lineage diversity."
                )
            else:
                missing.append(Missing(
                    family=fam,
                    reason=f"no reachable reviewer in family {fam}",
                ))
            continue
        candidates = by_family(fam)
        if candidates:
            pick = next((c for c in candidates if c.id not in picked), None)
            if pick is not None:
                picks.append(_annotate(pick, env))
                picked.add(pick.id)
            else:
                missing.append(Missing(
                    family=fam,
                    reason=f"all reviewers in family {fam} already selected",
                ))
        else:
            backfill = next(
                (s for s in eligible
                 if s.id not in picked
                 and s.entry.family != caller_family
                 and s.entry.family not in _TARGET_FAMILIES),
                None,
            )
            missing.append(Missing(
                family=fam,
                reason=f"no reachable reviewer in family {fam}",
            ))
            if backfill is not None:
                picks.append(_annotate(backfill, env))
                picked.add(backfill.id)
                nudges.append(
                    f"No {fam}-family reviewer reachable — using "
                    f"{backfill.id} ({backfill.entry.family}) as stand-in. "
                    "Install gemini (google) or codex/copilot (openai) "
                    "for full lineage diversity."
                )

    # Backfill from any remaining eligible if still under 2.
    if len(picks) < 2:
        for s in eligible:
            if len(picks) >= 2:
                break
            if s.id not in picked:
                picks.append(_annotate(s, env))
                picked.add(s.id)

    if not picks:
        base_note = (
            "No external reviewers reachable. Install codex, gemini, "
            "opencode, aider, or copilot (or set OPENAI_API_KEY / "
            "GEMINI_API_KEY) to enable cross-review."
        )
    elif len(picks) < 2:
        ids = ", ".join(p.id for p in picks)
        base_note = (
            f"Cross-review prefers ≥2 lineages alongside the caller. "
            f"Only {len(picks)} reachable ({ids}); install another to "
            "triangulate findings."
        )
    else:
        base_note = ""

    note = " ".join(p for p in [base_note, *nudges] if p).strip()
    return PickResult(picks=picks, missing=missing, note=note)


def roster_for(
    *,
    exclude_self: bool = True,
    only: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[ReviewerStatus]:
    """Roster filtered for caller convenience."""
    self_id = detect_self(env)
    items = roster_with_status(env)
    if only:
        match = next((s for s in items if s.id == only.lower()), None)
        return [match] if match else []
    if exclude_self and self_id:
        items = [s for s in items if not s.is_self]
    return items


def default_reviewer(
    env: Mapping[str, str] | None = None,
) -> ReviewerStatus | None:
    """First non-self reviewer (priority order)."""
    items = roster_for(exclude_self=True, env=env)
    return items[0] if items else None


def format_roster(env: Mapping[str, str] | None = None) -> str:
    """Pretty-print the roster for terminal output."""
    self_id = detect_self(env)
    items = roster_with_status(env)
    lines = []
    for s in items:
        if s.is_self:
            role = "self    "
        elif s.installed:
            role = "ready   "
        else:
            role = "install "
        lines.append(
            f"  {s.id.ljust(9)} {role}-- {s.entry.name} "
            f"({s.entry.invoke}) -- {s.entry.note}"
        )
    header = (
        f"Detected caller: {self_id}. "
        "Roster (ready = installed + non-self):"
        if self_id else "Caller unknown — full roster:"
    )
    return header + "\n" + "\n".join(lines)


__all__ = [
    "ROSTER",
    "ApiFallback",
    "Missing",
    "Pick",
    "PickResult",
    "Reachability",
    "ReviewerEntry",
    "ReviewerStatus",
    "default_reviewer",
    "detect_self",
    "format_roster",
    "is_installed",
    "is_reachable",
    "pick_reviewers",
    "roster_for",
    "roster_with_status",
]
