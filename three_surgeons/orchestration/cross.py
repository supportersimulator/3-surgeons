"""Cross-reviewer orchestrator — fan-out, timeout, fallback, merge.

Ported from IJFW's ``mcp-server/src/cross-orchestrator.js`` per the harvest
plan (2026-04-25 ContextDNA strategic doc). Adapted for 3-Surgeons.

WHY THIS EXISTS
---------------
:func:`run_cross_op` is the single entry point that turns a (mode, target)
request into structured findings:

    pick reviewers (roster)
      → build per-reviewer request payloads (dispatcher)
      → fan-out subprocess CLI calls with per-provider timeouts
      → fall back to API on CLI timeout or non-zero exit
      → optionally short-circuit once N responses settle (kill stragglers)
      → parse + merge per-mode (dispatcher)
      → write JSONL receipt
      → return merged findings + provenance

DESIGN
------
* Threading-based fan-out (matches the rest of 3-Surgeons; no asyncio).
* :class:`Dispatcher` and :class:`ApiCaller` are Protocols — caller
  injects them. Tests can pass stubs; production wires the real
  cross-dispatcher and api-client modules.
* Per-provider CLI timeouts mirror IJFW (codex 120s cold-start, gemini
  45s, anthropic 60s, api-mode 30s, default 90s).
* ``min_responses`` short-circuit: once N reviewers settle, an
  :class:`threading.Event` aborts the rest and they get an "aborted"
  sentinel result. Mirrors the IJFW ``runAc`` AbortController pattern.
* No I/O at module import — pure functions + dataclasses.

NOT GOALS
---------
* Not the dispatcher itself — :class:`Dispatcher` is a Protocol; the
  build/parse/merge logic lives in a separate module (next harvest pass).
* Not the API client — same story for :class:`ApiCaller`.
* Not a CLI — UX gating (confirm prompt, missing-family warnings) is
  caller-side; this module is library-only.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from three_surgeons.orchestration.roster import (
    Pick,
    PickResult,
    is_reachable,
    pick_reviewers,
)
from three_surgeons.receipts.store import ReceiptRecord, read_receipts, write_receipt

logger = logging.getLogger(__name__)


# ── Per-provider CLI timeout defaults (seconds) ─────────────────────────
#: Codex cold-start can exceed 120s; gemini is fast; anthropic in between.
PROVIDER_TIMEOUT_SEC: dict[str, float] = {
    "codex":     120.0,
    "gemini":     45.0,
    "anthropic":  60.0,
    "api-mode":   30.0,
}
DEFAULT_TIMEOUT_SEC: float = 90.0


def timeout_for_pick(pick: Pick, resolved_timeout_sec: float | None) -> float:
    """Per-pick timeout: explicit override > provider default > global default."""
    if resolved_timeout_sec is not None:
        return float(resolved_timeout_sec)
    return PROVIDER_TIMEOUT_SEC.get(pick.id, DEFAULT_TIMEOUT_SEC)


def parse_pos_int(
    raw: Any, fallback: int | None, *, min_v: int = 1, max_v: int = 2**31,
) -> int | None:
    """Parse a raw value to a positive int in [min_v, max_v]; fallback otherwise."""
    if raw is None or raw == "":
        return fallback
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return fallback
    if n < min_v or n > max_v:
        return fallback
    return n


# ── Angle assignment per mode/reviewer ──────────────────────────────────


def _audit_angle(_pick_id: str) -> str:
    return "general"


def _research_angle(pick_id: str) -> str:
    if pick_id in {"codex", "opencode", "aider"}:
        return "benchmarks"
    if pick_id == "claude":
        return "synthesis"
    return "citations"


def _critique_angle(pick_id: str) -> str:
    if pick_id in {"codex", "opencode", "aider"}:
        return "technical"
    if pick_id in {"gemini", "copilot"}:
        return "strategic"
    return "ux"


def angle_for(mode: str, pick_id: str) -> str:
    """Map (mode, reviewer) → angle string consumed by the dispatcher."""
    if mode == "audit":
        return _audit_angle(pick_id)
    if mode == "research":
        return _research_angle(pick_id)
    if mode == "critique":
        return _critique_angle(pick_id)
    raise ValueError(f"Unknown mode: {mode!r}")


# ── Result dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SpawnResult:
    """Raw return of :func:`spawn_cli`."""
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    aborted: bool


@dataclass(frozen=True)
class ApiResult:
    """What an :class:`ApiCaller` is expected to return."""
    status: str  #: "ok" | "failed"
    raw: str = ""
    error: str = ""


@dataclass(frozen=True)
class ExternalResult:
    """Result of one reviewer attempt — either via CLI or API fallback."""
    stdout: str
    stderr: str
    exit_code: int | None
    #: "ok" | "empty" | "failed" | "timeout" | "fallback-used" | "aborted" | None
    status: str | None
    source: str  #: "cli" | "api" | "none"
    elapsed_ms: float


@dataclass(frozen=True)
class AuditorResult:
    """Per-reviewer parsed findings + provenance, for the receipt."""
    pick_id: str
    family: str
    status: str
    source: str
    stderr: str
    exit_code: int | None
    elapsed_ms: float
    parsed: dict[str, Any]


@dataclass(frozen=True)
class CrossOpResult:
    """Return value of :func:`run_cross_op`."""
    merged: Any
    picks: list[Pick]
    missing: list[dict[str, Any]]
    note: str
    auditor_results: list[AuditorResult]
    duration_ms: float
    receipt: dict[str, Any] | None = None
    all_timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "merged": self.merged,
            "picks": [
                {"id": p.id, "family": p.entry.family,
                 "preferred_source": p.preferred_source}
                for p in self.picks
            ],
            "missing": list(self.missing),
            "note": self.note,
            "auditor_results": [
                {
                    "id": a.pick_id, "family": a.family, "status": a.status,
                    "source": a.source, "elapsed_ms": a.elapsed_ms,
                    "exit_code": a.exit_code, "stderr": a.stderr,
                    "parsed": a.parsed,
                }
                for a in self.auditor_results
            ],
            "duration_ms": self.duration_ms,
            "receipt": self.receipt,
            "all_timed_out": self.all_timed_out,
        }


# ── Dispatcher / API-caller Protocols (caller injects) ──────────────────


class Dispatcher(Protocol):
    """Per-mode payload builder + response parser + merger.

    Production implementation lives in a separate cross-dispatcher module
    (next harvest pass). Tests inject a stub.
    """

    def build_request(
        self, mode: str, target: str, pick_id: str, angle: str, swarm_config: Any,
    ) -> str: ...

    def parse_response(self, mode: str, stdout: str) -> dict[str, Any]: ...

    def merge_responses(
        self, mode: str, parsed_list: Sequence[dict[str, Any]],
    ) -> Any: ...

    def check_budget(
        self, *, target: str, picks: Sequence[Pick],
        receipts: Sequence[Mapping[str, Any]],
        session_start: float, env: Mapping[str, str],
    ) -> str | None: ...


class ApiCaller(Protocol):
    """API fallback hook. Returns :class:`ApiResult`."""

    def __call__(
        self, pick: Pick, mode: str, angle: str, target: str,
        env: Mapping[str, str], timeout_sec: float,
    ) -> ApiResult: ...


# ── spawn_cli: subprocess with timeout + abort ──────────────────────────


def spawn_cli(
    pick: Pick,
    request: str,
    timeout_sec: float,
    *,
    env: Mapping[str, str] | None = None,
    abort_event: threading.Event | None = None,
) -> SpawnResult | None:
    """Spawn the reviewer CLI, write ``request`` to stdin, return output.

    Returns ``None`` if the binary cannot be spawned (FileNotFoundError /
    OSError). Returns a :class:`SpawnResult` with ``timed_out=True`` on
    timeout, ``aborted=True`` if ``abort_event`` fires before the process
    finishes naturally.
    """
    if abort_event is not None and abort_event.is_set():
        return SpawnResult("", "aborted", None, False, True)

    parts = pick.entry.invoke.strip().split()
    if not parts:
        return None
    bin_name, args = parts[0], parts[1:]
    if shutil.which(bin_name) is None:
        return None

    proc_env = dict(os.environ)
    if env is not None:
        proc_env.update({k: v for k, v in env.items() if isinstance(v, str)})

    try:
        proc = subprocess.Popen(
            [bin_name, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
            text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        logger.debug("spawn_cli failed for %s: %s", pick.id, exc)
        return None

    abort_killed = {"flag": False}
    abort_thread: threading.Thread | None = None
    if abort_event is not None:
        def _watch() -> None:
            if abort_event.wait(timeout_sec + 1.0):
                if proc.poll() is None:
                    abort_killed["flag"] = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
        abort_thread = threading.Thread(target=_watch, daemon=True)
        abort_thread.start()

    try:
        stdout, stderr = proc.communicate(input=request, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.communicate(timeout=2.0)
        except Exception:
            pass
        return SpawnResult("", "timeout", None, True, False)

    if abort_killed["flag"]:
        return SpawnResult("", "aborted", None, False, True)

    return SpawnResult(stdout or "", stderr or "", proc.returncode, False, False)


# ── fire_external: CLI with API-key fallback ────────────────────────────


def _extract_api_params(request: str) -> tuple[str, str, str]:
    """Pull mode/angle/target out of a built request payload.

    Mirrors IJFW's regex-based extraction so an API fallback can rebuild
    the request server-side without re-running ``build_request``.
    """
    import re

    m_mode = re.search(r"^Mode:\s+(\S+)", request, re.MULTILINE)
    m_angle = re.search(r"^Angle:\s+(\S+)", request, re.MULTILINE)
    m_target = re.search(r"## Target\s*\n\n([\s\S]*)$", request)
    mode = m_mode.group(1) if m_mode else "audit"
    angle = m_angle.group(1) if m_angle else "general"
    target = m_target.group(1).strip() if m_target else request
    return mode, angle, target


def fire_external(
    pick: Pick,
    request: str,
    timeout_sec: float,
    env: Mapping[str, str],
    *,
    api_caller: ApiCaller | None = None,
    abort_event: threading.Event | None = None,
    spawn_fn: Callable[..., SpawnResult | None] = spawn_cli,
) -> ExternalResult:
    """Try CLI first; on timeout/failure fall back to API if reachable.

    A CLI **timeout IS fallback-eligible** — a slow CLI gets bypassed by
    the API when one is available, since the API uses its own (shorter)
    budget. Result ``status`` ends up either ``"fallback-used"`` (API
    succeeded) or the original ``"timeout"`` (both paths exhausted).
    """
    t0 = time.monotonic()
    def _elapsed_ms() -> float:
        return (time.monotonic() - t0) * 1000.0

    api_timeout = PROVIDER_TIMEOUT_SEC["api-mode"]

    # API-only pick (preferred_source == "api") — skip CLI spawn entirely.
    if (
        pick.preferred_source == "api"
        and pick.entry.api_fallback is not None
        and api_caller is not None
        and is_reachable(pick.id, env=env).api
    ):
        if abort_event is not None and abort_event.is_set():
            return ExternalResult("", "aborted", None, "aborted", "none", _elapsed_ms())
        mode, angle, target = _extract_api_params(request)
        api_res = api_caller(pick, mode, angle, target, env, api_timeout)
        if api_res.status == "ok":
            return ExternalResult(api_res.raw, "", 0, "fallback-used", "api", _elapsed_ms())
        return ExternalResult("", api_res.error, None, "failed", "none", _elapsed_ms())

    raw = spawn_fn(pick, request, timeout_sec, env=env, abort_event=abort_event)

    if raw is not None and raw.aborted:
        return ExternalResult("", "aborted", None, "aborted", "none", _elapsed_ms())

    if raw is not None and raw.timed_out:
        if (
            pick.entry.api_fallback is not None
            and api_caller is not None
            and is_reachable(pick.id, env=env).api
        ):
            mode, angle, target = _extract_api_params(request)
            api_res = api_caller(pick, mode, angle, target, env, api_timeout)
            if api_res.status == "ok":
                return ExternalResult(
                    api_res.raw, "", 0, "fallback-used", "api", _elapsed_ms(),
                )
        return ExternalResult("", "timeout", None, "timeout", "none", _elapsed_ms())

    cli_ok = raw is not None and raw.exit_code == 0
    if not cli_ok and (
        pick.entry.api_fallback is not None
        and api_caller is not None
        and is_reachable(pick.id, env=env).api
    ):
        mode, angle, target = _extract_api_params(request)
        api_res = api_caller(pick, mode, angle, target, env, api_timeout)
        if api_res.status == "ok":
            return ExternalResult(
                api_res.raw, "", 0, "fallback-used", "api", _elapsed_ms(),
            )
        return ExternalResult("", api_res.error, None, "failed", "none", _elapsed_ms())

    if raw is None:
        return ExternalResult("", "spawn error", None, "failed", "none", _elapsed_ms())

    return ExternalResult(
        raw.stdout, raw.stderr, raw.exit_code, None, "cli", _elapsed_ms(),
    )


# ── fan-out + min-responses short-circuit ───────────────────────────────


def fan_out(
    tasks: Sequence[Callable[[], Any]],
    concurrency: int = 3,
) -> list[Any]:
    """Rolling concurrency window; runs ``tasks`` and preserves order."""
    total = len(tasks)
    results: list[Any] = [None] * total
    next_idx = {"i": 0}
    lock = threading.Lock()

    def _worker() -> None:
        while True:
            with lock:
                if next_idx["i"] >= total:
                    return
                i = next_idx["i"]
                next_idx["i"] += 1
            results[i] = tasks[i]()

    threads = [
        threading.Thread(target=_worker, daemon=True)
        for _ in range(min(concurrency, total))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def min_responses_fan_out(
    requests: Sequence[Mapping[str, Any]],
    *,
    resolved_timeout_sec: float | None,
    env: Mapping[str, str],
    concurrency: int,
    min_responses: int,
    abort_event: threading.Event,
    fire_fn: Callable[..., ExternalResult] = fire_external,
    api_caller: ApiCaller | None = None,
) -> list[ExternalResult]:
    """Abort stragglers once ``min_responses`` reviewers settle.

    ``requests`` is a sequence of ``{"pick": Pick, "payload": str}`` dicts.
    """
    total = len(requests)
    results: list[ExternalResult | None] = [None] * total
    state = {"settled": 0, "next": 0}
    lock = threading.Lock()
    threshold = min(min_responses, total) if min_responses > 0 else total

    def _worker() -> None:
        while True:
            with lock:
                if abort_event.is_set() or state["next"] >= total:
                    return
                i = state["next"]
                state["next"] += 1
            req = requests[i]
            pick: Pick = req["pick"]
            payload: str = req["payload"]
            res = fire_fn(
                pick, payload,
                timeout_for_pick(pick, resolved_timeout_sec),
                env,
                api_caller=api_caller,
                abort_event=abort_event,
            )
            with lock:
                results[i] = res
                state["settled"] += 1
                if state["settled"] >= threshold:
                    abort_event.set()

    threads = [
        threading.Thread(target=_worker, daemon=True)
        for _ in range(min(concurrency, total))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for j in range(total):
        if results[j] is None:
            results[j] = ExternalResult(
                "", "aborted", None, "aborted", "none", 0.0,
            )
    return [r for r in results if r is not None]


def count_items(parsed: Mapping[str, Any]) -> int:
    """Number of findings across audit/critique items + research consensus."""
    items = parsed.get("items")
    if isinstance(items, list):
        return len(items)
    consensus = parsed.get("consensus")
    if isinstance(consensus, list):
        contested = parsed.get("contested") or []
        return len(consensus) + (len(contested) if isinstance(contested, list) else 0)
    return 0


# ── run_cross_op: the orchestration entry point ─────────────────────────


def run_cross_op(
    *,
    mode: str,
    target: str,
    dispatcher: Dispatcher,
    project_dir: str | None = None,
    env: Mapping[str, str] | None = None,
    run_stamp: str | None = None,
    only: str | None = None,
    per_auditor_timeout_sec: float | None = None,
    min_responses: int = 0,
    quiet: bool = True,
    api_caller: ApiCaller | None = None,
    swarm_config: Any = None,
    pick_strategy: str = "diversity",
    fire_fn: Callable[..., ExternalResult] = fire_external,
    receipt_writer: Callable[..., Any] | None = None,
    receipts_reader: Callable[..., Sequence[Mapping[str, Any]]] = read_receipts,
) -> CrossOpResult:
    """Run a cross-reviewer operation end-to-end.

    Steps mirror :func:`runCrossOp` in IJFW:
      1. roster pick (diversity by default)
      2. budget guard (caller-provided dispatcher.check_budget)
      3. build per-pick payloads
      4. fan-out fire_external with optional min_responses short-circuit
      5. parse + classify per-pick result
      6. all-timeout guard
      7. merge
      8. write receipt
      9. return CrossOpResult

    UX gating (the ``--confirm`` prompt and stderr warnings) lives in the
    CLI layer; this function is library-only and never reads stdin.
    """
    project_dir = project_dir or os.getcwd()
    env = env if env is not None else os.environ
    run_stamp = run_stamp or _utc_now_iso()

    start = time.monotonic()

    abort_event = threading.Event()

    # Resolve timeout from explicit > env > default
    raw_timeout = env.get("IJFW_AUDIT_TIMEOUT_SEC") if hasattr(env, "get") else None
    env_timeout = parse_pos_int(raw_timeout, None, min_v=1, max_v=3600)
    resolved_timeout = per_auditor_timeout_sec if per_auditor_timeout_sec else env_timeout

    # 1. Pick reviewers
    pick_result: PickResult = pick_reviewers(
        env=env, strategy=pick_strategy, only=only,
    )
    picks = pick_result.picks
    missing = pick_result.missing
    note = pick_result.note

    if not picks:
        return CrossOpResult(
            merged=None, picks=[], missing=missing, note=note,
            auditor_results=[], duration_ms=(time.monotonic() - start) * 1000.0,
        )

    # 2. Budget guard (dispatcher decides)
    session_start = time.time() - _process_uptime_sec()
    prior_receipts = receipts_reader(project_dir)
    budget_msg = dispatcher.check_budget(
        target=target, picks=picks, receipts=prior_receipts,
        session_start=session_start, env=env,
    )
    if budget_msg:
        # Library doesn't print; surface via note for the caller.
        return CrossOpResult(
            merged=None, picks=picks, missing=missing,
            note=f"{note} | budget: {budget_msg}".strip(" |"),
            auditor_results=[], duration_ms=(time.monotonic() - start) * 1000.0,
        )

    # 3. Build per-pick payloads
    requests = [
        {
            "pick": pick,
            "payload": dispatcher.build_request(
                mode, target, pick.id, angle_for(mode, pick.id), swarm_config,
            ),
        }
        for pick in picks
    ]

    # 4. Concurrency parsing
    raw_conc = env.get("IJFW_AUDIT_CONCURRENCY") if hasattr(env, "get") else None
    conc_parsed = parse_pos_int(raw_conc, None, min_v=1, max_v=16) if raw_conc else None
    concurrency = conc_parsed if conc_parsed is not None else 3

    # 5. Fire
    if min_responses and 0 < min_responses < len(picks):
        raw_results = min_responses_fan_out(
            requests,
            resolved_timeout_sec=resolved_timeout,
            env=env,
            concurrency=concurrency,
            min_responses=min_responses,
            abort_event=abort_event,
            fire_fn=fire_fn,
            api_caller=api_caller,
        )
    else:
        tasks = [
            (lambda p=req["pick"], pl=req["payload"]: fire_fn(
                p, pl, timeout_for_pick(p, resolved_timeout),
                env, api_caller=api_caller,
            ))
            for req in requests
        ]
        raw_results = fan_out(tasks, concurrency)

    # 6. Classify per-pick
    auditor_results: list[AuditorResult] = []
    for i, raw in enumerate(raw_results):
        pick = picks[i]
        if raw is None:
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family, status="failed",
                source="none", stderr="spawn error", exit_code=None,
                elapsed_ms=0.0,
                parsed={"items": [], "prose": f"[{pick.id}: spawn failed]"},
            ))
            continue

        stderr_snip = (raw.stderr or "")[:500]

        if raw.status == "aborted":
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family, status="aborted",
                source="none", stderr=stderr_snip, exit_code=None,
                elapsed_ms=raw.elapsed_ms,
                parsed={"items": [], "prose": f"[{pick.id}: aborted]"},
            ))
            continue
        if raw.status == "timeout":
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family, status="timeout",
                source="none", stderr=stderr_snip, exit_code=None,
                elapsed_ms=raw.elapsed_ms,
                parsed={"items": [], "prose": f"[{pick.id}: timeout]"},
            ))
            continue
        if raw.status == "failed":
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family, status="failed",
                source="none", stderr=stderr_snip, exit_code=raw.exit_code,
                elapsed_ms=raw.elapsed_ms,
                parsed={"items": [], "prose": f"[{pick.id}: failed]"},
            ))
            continue
        if raw.status == "fallback-used":
            parsed = dispatcher.parse_response(mode, raw.stdout)
            n = count_items(parsed)
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family,
                status="empty" if n == 0 else "fallback-used",
                source="api", stderr=stderr_snip, exit_code=0,
                elapsed_ms=raw.elapsed_ms, parsed=parsed,
            ))
            continue

        # CLI path (status is None → normal exit)
        if raw.exit_code != 0 or (stderr_snip and not raw.stdout.strip()):
            auditor_results.append(AuditorResult(
                pick_id=pick.id, family=pick.entry.family, status="failed",
                source=raw.source or "none", stderr=stderr_snip,
                exit_code=raw.exit_code, elapsed_ms=raw.elapsed_ms,
                parsed={
                    "items": [],
                    "prose": f"[{pick.id}: exited {raw.exit_code}]",
                },
            ))
            continue

        parsed = dispatcher.parse_response(mode, raw.stdout)
        n = count_items(parsed)
        auditor_results.append(AuditorResult(
            pick_id=pick.id, family=pick.entry.family,
            status="empty" if n == 0 else "ok",
            source=raw.source or "cli", stderr=stderr_snip,
            exit_code=raw.exit_code, elapsed_ms=raw.elapsed_ms, parsed=parsed,
        ))

    # 7. All-timeout guard
    duration_ms = (time.monotonic() - start) * 1000.0
    if auditor_results and all(r.status == "timeout" for r in auditor_results):
        return CrossOpResult(
            merged=None, picks=picks, missing=missing, note=note,
            auditor_results=auditor_results, duration_ms=duration_ms,
            all_timed_out=True,
        )

    # 8. Merge
    parsed_list = [r.parsed for r in auditor_results]
    merged = dispatcher.merge_responses(mode, parsed_list)

    # 9. Findings shape per mode
    if mode in {"audit", "critique"}:
        findings_items = merged if isinstance(merged, list) else []
        findings: dict[str, Any] = {"items": list(findings_items)}
    else:
        findings = merged if isinstance(merged, dict) else {"value": merged}

    # 10. Receipt
    record = ReceiptRecord(
        mode=mode,
        timestamp=run_stamp,
        auditors=[
            {
                "id": a.pick_id,
                "family": a.family,
                "status": a.status,
                "source": a.source,
                "elapsed_ms": a.elapsed_ms,
                **({"error": a.stderr, "exit_code": a.exit_code}
                   if a.status in {"failed", "timeout"} else {}),
            }
            for a in auditor_results
        ],
        findings=findings,
        duration_ms=duration_ms,
        extra={"target": target, "run_stamp": run_stamp, "v": 1},
    )
    receipt_dict = record.to_dict()

    writer = receipt_writer or write_receipt
    try:
        writer(project_dir, record)
    except Exception as exc:  # pragma: no cover — never break the run on receipt I/O
        logger.warning("receipt write failed: %s", exc)

    return CrossOpResult(
        merged=merged, picks=picks, missing=missing, note=note,
        auditor_results=auditor_results, duration_ms=duration_ms,
        receipt=receipt_dict, all_timed_out=False,
    )


# ── helpers ─────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _process_uptime_sec() -> float:
    """Best-effort process uptime in seconds (for budget windowing)."""
    try:
        import psutil  # type: ignore[import-not-found]
        return time.time() - psutil.Process().create_time()
    except Exception:
        return 0.0


__all__ = [
    "PROVIDER_TIMEOUT_SEC",
    "DEFAULT_TIMEOUT_SEC",
    "ApiCaller",
    "ApiResult",
    "AuditorResult",
    "CrossOpResult",
    "Dispatcher",
    "ExternalResult",
    "SpawnResult",
    "angle_for",
    "count_items",
    "fan_out",
    "fire_external",
    "min_responses_fan_out",
    "parse_pos_int",
    "run_cross_op",
    "spawn_cli",
    "timeout_for_pick",
]
