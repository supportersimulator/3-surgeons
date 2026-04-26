"""Tests for three_surgeons/orchestration/cross.py — IJFW Phase 2b harvest."""
from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Sequence
from unittest.mock import patch

import pytest

from three_surgeons.orchestration import cross, roster
from three_surgeons.orchestration.cross import (
    DEFAULT_TIMEOUT_SEC,
    PROVIDER_TIMEOUT_SEC,
    ApiResult,
    AuditorResult,
    CrossOpResult,
    ExternalResult,
    SpawnResult,
    angle_for,
    count_items,
    fan_out,
    fire_external,
    min_responses_fan_out,
    parse_pos_int,
    run_cross_op,
    spawn_cli,
    timeout_for_pick,
)
from three_surgeons.orchestration.roster import Pick, ReviewerEntry


@pytest.fixture(autouse=True)
def reset_roster_cache():
    roster._reset_cache()
    yield
    roster._reset_cache()


# ── Stub dispatcher / API caller ─────────────────────────────────────────


class StubDispatcher:
    """Minimal dispatcher that records calls and returns predictable shape."""

    def __init__(self, *, budget: str | None = None,
                 parsed_items: int = 1, merge_fn=None):
        self.budget = budget
        self.parsed_items = parsed_items
        self.merge_fn = merge_fn or (lambda mode, parsed_list: [
            item for p in parsed_list for item in (p.get("items") or [])
        ])
        self.build_calls: list[tuple] = []
        self.parse_calls: list[tuple] = []
        self.merge_calls: list[tuple] = []
        self.budget_calls: list[dict] = []

    def build_request(self, mode, target, pick_id, angle, swarm_config):
        self.build_calls.append((mode, target, pick_id, angle))
        return f"Mode: {mode}\nAngle: {angle}\n\n## Target\n\n{target}"

    def parse_response(self, mode, stdout):
        self.parse_calls.append((mode, stdout))
        return {"items": [{"raw": stdout, "n": i} for i in range(self.parsed_items)]}

    def merge_responses(self, mode, parsed_list):
        self.merge_calls.append((mode, list(parsed_list)))
        return self.merge_fn(mode, parsed_list)

    def check_budget(self, *, target, picks, receipts, session_start, env):
        self.budget_calls.append({"target": target, "picks": list(picks)})
        return self.budget


def _ok_api_caller(pick, mode, angle, target, env, timeout_sec):
    return ApiResult(status="ok", raw=f"api-out:{pick.id}")


def _fail_api_caller(pick, mode, angle, target, env, timeout_sec):
    return ApiResult(status="failed", error="boom")


# ── parse_pos_int ────────────────────────────────────────────────────────


def test_parse_pos_int_valid():
    assert parse_pos_int("5", 1) == 5


def test_parse_pos_int_fallback_on_garbage():
    assert parse_pos_int("nope", 7) == 7


def test_parse_pos_int_fallback_on_zero():
    assert parse_pos_int("0", 3, min_v=1) == 3


def test_parse_pos_int_fallback_on_too_big():
    assert parse_pos_int("999", 5, min_v=1, max_v=10) == 5


def test_parse_pos_int_handles_none_and_empty():
    assert parse_pos_int(None, 9) == 9
    assert parse_pos_int("", 9) == 9


# ── timeout_for_pick / angle_for / count_items ───────────────────────────


def _pick(id_: str, family: str = "openai", *, preferred_source: str = "cli",
          api_fallback=True) -> Pick:
    entry = next((e for e in roster.ROSTER if e.id == id_), None)
    if entry is None:
        # Synthesise a tiny entry for tests targeting fictional ids.
        entry = ReviewerEntry(
            id=id_, family=family, name=id_, invoke=f"{id_} run",
            note="test", env_keys=(), cmd_keys=(),
            api_fallback=None,
        )
    return Pick(entry=entry, preferred_source=preferred_source)


def test_timeout_for_pick_explicit_override():
    p = _pick("codex")
    assert timeout_for_pick(p, 10.0) == 10.0


def test_timeout_for_pick_provider_default():
    p = _pick("codex")
    assert timeout_for_pick(p, None) == PROVIDER_TIMEOUT_SEC["codex"]


def test_timeout_for_pick_global_default():
    p = _pick("opencode")  # not in PROVIDER_TIMEOUT_SEC
    assert timeout_for_pick(p, None) == DEFAULT_TIMEOUT_SEC


def test_angle_for_audit_is_general():
    assert angle_for("audit", "anything") == "general"


def test_angle_for_research_codex_is_benchmarks():
    assert angle_for("research", "codex") == "benchmarks"


def test_angle_for_research_claude_is_synthesis():
    assert angle_for("research", "claude") == "synthesis"


def test_angle_for_critique_codex_is_technical():
    assert angle_for("critique", "codex") == "technical"


def test_angle_for_unknown_mode_raises():
    with pytest.raises(ValueError):
        angle_for("totally-fake-mode", "claude")


def test_count_items_with_items_list():
    assert count_items({"items": [1, 2, 3]}) == 3


def test_count_items_with_consensus():
    assert count_items({"consensus": [1, 2], "contested": [3]}) == 3


def test_count_items_empty():
    assert count_items({}) == 0


# ── spawn_cli (mocked subprocess) ────────────────────────────────────────


class _FakeProc:
    def __init__(self, *, stdout="ok-out", stderr="", exit_code=0,
                 timeout_on=None):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = exit_code
        self._timeout_on = timeout_on
        self._kill_called = False

    def communicate(self, input=None, timeout=None):
        if self._timeout_on:
            import subprocess
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return self._stdout, self._stderr

    def kill(self):
        self._kill_called = True

    def poll(self):
        return self.returncode


def test_spawn_cli_returns_none_for_missing_binary():
    p = _pick("totally-missing-bin-xyz")
    with patch.object(cross.shutil, "which", return_value=None):
        assert spawn_cli(p, "req", 1.0) is None


def test_spawn_cli_returns_aborted_when_event_already_set():
    p = _pick("codex")
    ev = threading.Event(); ev.set()
    with patch.object(cross.shutil, "which", return_value="/x/codex"):
        result = spawn_cli(p, "req", 1.0, abort_event=ev)
    assert result is not None
    assert result.aborted is True
    assert result.stderr == "aborted"


def test_spawn_cli_success():
    p = _pick("codex")
    fake = _FakeProc(stdout="hello", stderr="", exit_code=0)
    with (
        patch.object(cross.shutil, "which", return_value="/x/codex"),
        patch.object(cross.subprocess, "Popen", return_value=fake),
    ):
        result = spawn_cli(p, "req", 1.0)
    assert result is not None
    assert result.stdout == "hello"
    assert result.exit_code == 0
    assert result.timed_out is False


def test_spawn_cli_timeout():
    p = _pick("codex")
    fake = _FakeProc(timeout_on=True)
    with (
        patch.object(cross.shutil, "which", return_value="/x/codex"),
        patch.object(cross.subprocess, "Popen", return_value=fake),
    ):
        result = spawn_cli(p, "req", 0.01)
    assert result is not None
    assert result.timed_out is True
    assert result.stderr == "timeout"
    assert fake._kill_called is True


# ── fire_external ────────────────────────────────────────────────────────


def _stub_spawn_ok(*args, **kwargs):
    return SpawnResult(stdout="cli-out", stderr="", exit_code=0,
                       timed_out=False, aborted=False)


def _stub_spawn_timeout(*args, **kwargs):
    return SpawnResult(stdout="", stderr="timeout", exit_code=None,
                       timed_out=True, aborted=False)


def _stub_spawn_failed(*args, **kwargs):
    return SpawnResult(stdout="", stderr="bad", exit_code=2,
                       timed_out=False, aborted=False)


def _stub_spawn_aborted(*args, **kwargs):
    return SpawnResult(stdout="", stderr="aborted", exit_code=None,
                       timed_out=False, aborted=True)


def test_fire_external_cli_ok():
    p = _pick("codex")
    res = fire_external(p, "req", 60.0, env={}, spawn_fn=_stub_spawn_ok)
    assert res.status is None
    assert res.source == "cli"
    assert res.stdout == "cli-out"


def test_fire_external_cli_timeout_falls_back_to_api():
    p = _pick("codex", preferred_source="cli")  # codex has api_fallback in ROSTER
    res = fire_external(
        p, "Mode: audit\nAngle: general\n\n## Target\n\nx",
        60.0, env={"OPENAI_API_KEY": "sk-x"},
        api_caller=_ok_api_caller,
        spawn_fn=_stub_spawn_timeout,
    )
    assert res.status == "fallback-used"
    assert res.source == "api"
    assert "api-out:codex" in res.stdout


def test_fire_external_cli_timeout_no_fallback_when_api_unreachable():
    p = _pick("codex")
    res = fire_external(
        p, "req", 60.0, env={},  # no OPENAI_API_KEY
        api_caller=_ok_api_caller,
        spawn_fn=_stub_spawn_timeout,
    )
    assert res.status == "timeout"
    assert res.source == "none"


def test_fire_external_cli_failed_falls_back_to_api():
    p = _pick("codex")
    res = fire_external(
        p, "Mode: audit\nAngle: general\n\n## Target\n\nx",
        60.0, env={"OPENAI_API_KEY": "sk-x"},
        api_caller=_ok_api_caller,
        spawn_fn=_stub_spawn_failed,
    )
    assert res.status == "fallback-used"


def test_fire_external_api_only_pick_skips_cli():
    p = _pick("codex", preferred_source="api")
    spawn_called = {"n": 0}

    def _spy_spawn(*args, **kwargs):
        spawn_called["n"] += 1
        return _stub_spawn_ok()

    res = fire_external(
        p, "Mode: audit\nAngle: general\n\n## Target\n\nx",
        60.0, env={"OPENAI_API_KEY": "sk-x"},
        api_caller=_ok_api_caller,
        spawn_fn=_spy_spawn,
    )
    assert spawn_called["n"] == 0
    assert res.status == "fallback-used"
    assert res.source == "api"


def test_fire_external_aborted():
    p = _pick("codex")
    res = fire_external(p, "req", 60.0, env={}, spawn_fn=_stub_spawn_aborted)
    assert res.status == "aborted"


# ── fan_out ──────────────────────────────────────────────────────────────


def test_fan_out_preserves_order():
    tasks = [(lambda i=i: i * 2) for i in range(5)]
    out = fan_out(tasks, concurrency=2)
    assert out == [0, 2, 4, 6, 8]


def test_fan_out_handles_empty():
    assert fan_out([], concurrency=3) == []


def test_fan_out_concurrency_capped_to_task_count():
    out = fan_out([lambda: 1, lambda: 2], concurrency=10)
    assert sorted(out) == [1, 2]


# ── min_responses_fan_out ────────────────────────────────────────────────


def _slow_then_fast_fire(slow_ids: set[str]):
    """Spawn-fn surrogate: codex slow, others fast."""
    def _fire(pick, payload, timeout_sec, env, *, api_caller=None,
              abort_event=None):
        if pick.id in slow_ids:
            # Honor abort_event with a sleep loop.
            for _ in range(50):  # up to 5s
                if abort_event and abort_event.is_set():
                    return ExternalResult("", "aborted", None, "aborted",
                                          "none", 0.0)
                time.sleep(0.1)
            return ExternalResult("slow", "", 0, None, "cli", 5000.0)
        return ExternalResult("fast", "", 0, None, "cli", 10.0)
    return _fire


def test_min_responses_aborts_stragglers():
    picks = [_pick("codex"), _pick("gemini"), _pick("opencode")]
    requests = [{"pick": p, "payload": "x"} for p in picks]
    abort = threading.Event()
    results = min_responses_fan_out(
        requests,
        resolved_timeout_sec=5.0,
        env={},
        concurrency=3,
        min_responses=2,
        abort_event=abort,
        fire_fn=_slow_then_fast_fire(slow_ids={"codex"}),
    )
    assert len(results) == 3
    # Codex should be aborted; the two fast ones should be ok.
    codex_res = results[0]
    assert codex_res.status == "aborted"
    assert results[1].stdout == "fast"
    assert results[2].stdout == "fast"
    assert abort.is_set()


def test_min_responses_zero_runs_all():
    picks = [_pick("codex"), _pick("gemini")]
    requests = [{"pick": p, "payload": "x"} for p in picks]
    abort = threading.Event()

    def _fast(pick, payload, timeout_sec, env, *, api_caller=None,
              abort_event=None):
        return ExternalResult(pick.id, "", 0, None, "cli", 1.0)

    results = min_responses_fan_out(
        requests, resolved_timeout_sec=5.0, env={}, concurrency=2,
        min_responses=2,  # equals total → no short-circuit
        abort_event=abort, fire_fn=_fast,
    )
    assert {r.stdout for r in results} == {"codex", "gemini"}


# ── run_cross_op (end-to-end with stubs) ─────────────────────────────────


def _fire_returning(stdout: str = "out"):
    def _fn(pick, payload, timeout_sec, env, *, api_caller=None,
            abort_event=None):
        return ExternalResult(stdout, "", 0, None, "cli", 1.0)
    return _fn


def test_run_cross_op_no_picks_returns_empty(tmp_path):
    disp = StubDispatcher()
    with patch.object(roster.shutil, "which", return_value=None):
        result = run_cross_op(
            mode="audit", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
        )
    assert result.merged is None
    assert result.picks == []


def test_run_cross_op_budget_blocks(tmp_path):
    disp = StubDispatcher(budget="too expensive")
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="audit", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
        )
    assert result.merged is None
    assert "budget" in result.note.lower()


def test_run_cross_op_full_flow_writes_receipt(tmp_path):
    disp = StubDispatcher(parsed_items=2)
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="audit", target="check this", dispatcher=disp,
            project_dir=str(tmp_path), env={},
            fire_fn=_fire_returning(stdout="audit-output"),
        )
    assert result.merged is not None
    assert result.receipt is not None
    assert result.receipt["mode"] == "audit"
    # Each pick should have produced an AuditorResult.
    assert len(result.auditor_results) == len(result.picks)
    # Findings shape for audit mode is {"items": [...]}.
    assert "items" in result.receipt["findings"]


def test_run_cross_op_classifies_timeout(tmp_path):
    disp = StubDispatcher()

    def _all_timeout(pick, payload, timeout_sec, env, *, api_caller=None,
                     abort_event=None):
        return ExternalResult("", "timeout", None, "timeout", "none", 0.0)

    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="audit", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
            fire_fn=_all_timeout,
        )
    assert result.all_timed_out is True
    assert all(r.status == "timeout" for r in result.auditor_results)


def test_run_cross_op_classifies_failed_via_nonzero_exit(tmp_path):
    disp = StubDispatcher()

    def _fail(pick, payload, timeout_sec, env, *, api_caller=None,
              abort_event=None):
        return ExternalResult("", "stderr-msg", 7, None, "cli", 1.0)

    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="critique", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
            fire_fn=_fail,
        )
    assert all(r.status == "failed" for r in result.auditor_results)


def test_run_cross_op_only_filter(tmp_path):
    disp = StubDispatcher()
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="audit", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
            only="gemini",
            fire_fn=_fire_returning(),
        )
    assert len(result.picks) == 1
    assert result.picks[0].id == "gemini"


def test_run_cross_op_to_dict_serialisable(tmp_path):
    disp = StubDispatcher()
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = run_cross_op(
            mode="audit", target="t", dispatcher=disp,
            project_dir=str(tmp_path), env={},
            fire_fn=_fire_returning(),
        )
    d = result.to_dict()
    assert "merged" in d and "picks" in d and "auditor_results" in d
    # Nothing in here should be a dataclass; everything plain dicts/lists/scalars.
    import json
    json.dumps(d, default=str)  # must not raise
