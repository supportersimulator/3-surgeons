"""Comprehensive tests for the capabilities adapter system.

Covers:
- Protocol compliance (SurgeryAdapter runtime_checkable)
- StandaloneAdapter (no-op correctness)
- CompositeAdapter (fan-out, isolation, chaining, gating)
- RedisAdapter (telemetry writes, failure resilience)
- GitAdapter (topic enrichment, subprocess failure)
- ContextDNAAdapter (HTTP POST, gate, failure counting)
- ObservabilityAdapter (SQLite writes, WAL mode)
- Detection probes + TTL cache (auto_detect)
- AdapterContext (lifecycle, fallback, close)

No live Redis, HTTP, or git required — all external dependencies are mocked.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, call, patch, patch as mock_patch

import pytest

from three_surgeons.adapters._protocol import Capability, GateBlockedError, SurgeryAdapter
from three_surgeons.adapters._standalone import StandaloneAdapter
from three_surgeons.adapters._composite import CompositeAdapter
from three_surgeons.adapters import AdapterContext, get_standalone


# ── Helpers ──────────────────────────────────────────────────────────────


class _FullAdapter:
    """Minimal adapter that satisfies every hook in the Protocol."""

    @property
    def capabilities(self) -> Capability:
        return Capability.NONE

    @property
    def thread_safe(self) -> bool:
        return True

    def on_init(self) -> None: pass
    def on_workflow_start(self, operation: str, topic: str) -> None: pass
    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None: pass
    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None: pass
    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None: pass
    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None: pass
    def enrich_topic(self, topic: str, operation: str) -> str: return topic
    def check_gate(self, operation: str) -> Optional[str]: return None
    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None: pass
    def close(self) -> None: pass


class _IncompleteAdapter:
    """Missing several required Protocol hooks."""
    @property
    def capabilities(self) -> Capability:
        return Capability.NONE

    # Intentionally omits: thread_safe, on_init, on_workflow_start, on_cost,
    # on_cross_exam_logged, on_error, enrich_topic, check_gate,
    # on_user_action, close


class _BlockingAdapter(StandaloneAdapter):
    """Returns a gate-block reason from check_gate."""
    def check_gate(self, operation: str) -> Optional[str]:
        return "blocked by test"


class _RaisingAdapter(StandaloneAdapter):
    """Raises on every hook — used to test composite isolation."""
    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        raise RuntimeError("on_cost explosion")

    def enrich_topic(self, topic: str, operation: str) -> str:
        raise RuntimeError("enrich_topic explosion")

    def check_gate(self, operation: str) -> Optional[str]:
        raise RuntimeError("check_gate explosion")


# ══════════════════════════════════════════════════════════════════════════
# 1. Protocol compliance
# ══════════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    """SurgeryAdapter is runtime_checkable — isinstance checks work."""

    def test_standalone_satisfies_protocol(self):
        adapter = StandaloneAdapter()
        assert isinstance(adapter, SurgeryAdapter)

    def test_composite_satisfies_protocol(self):
        adapter = CompositeAdapter([StandaloneAdapter()])
        assert isinstance(adapter, SurgeryAdapter)

    def test_full_mock_adapter_satisfies_protocol(self):
        adapter = _FullAdapter()
        assert isinstance(adapter, SurgeryAdapter)

    def test_incomplete_adapter_does_not_satisfy_protocol(self):
        adapter = _IncompleteAdapter()
        # runtime_checkable only checks for presence of methods/properties
        # the incomplete adapter is missing most hooks so isinstance returns False
        assert not isinstance(adapter, SurgeryAdapter)


# ══════════════════════════════════════════════════════════════════════════
# 2. StandaloneAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestStandaloneAdapter:
    """All hooks are no-ops, capabilities == NONE, thread_safe == True."""

    @pytest.fixture
    def adapter(self):
        return StandaloneAdapter()

    def test_capabilities_is_none(self, adapter):
        assert adapter.capabilities == Capability.NONE

    def test_thread_safe_is_true(self, adapter):
        assert adapter.thread_safe is True

    def test_on_init_no_raise(self, adapter):
        adapter.on_init()  # must not raise

    def test_on_workflow_start_no_raise(self, adapter):
        adapter.on_workflow_start("cross_examine", "some topic")

    def test_on_workflow_end_no_raise(self, adapter):
        adapter.on_workflow_end("cross_examine", "some topic", {"result": "ok"})

    def test_on_workflow_end_with_error_no_raise(self, adapter):
        adapter.on_workflow_end("cross_examine", "topic", None,
                                error=RuntimeError("test"))

    def test_on_cost_various_inputs_no_raise(self, adapter):
        adapter.on_cost("cardiologist", 0.0, "cross_examine")
        adapter.on_cost("neurologist", 9.999, "consult")
        adapter.on_cost("atlas", 0.001, "consensus")

    def test_on_cross_exam_logged_no_raise(self, adapter):
        adapter.on_cross_exam_logged("topic", {"key": "value"})

    def test_on_error_no_raise(self, adapter):
        adapter.on_error("cross_examine", ValueError("oops"), {"ctx": 1})

    def test_enrich_topic_returns_topic_unchanged(self, adapter):
        result = adapter.enrich_topic("my topic", "cross_examine")
        assert result == "my topic"

    def test_enrich_topic_empty_string(self, adapter):
        assert adapter.enrich_topic("", "consult") == ""

    def test_check_gate_returns_none(self, adapter):
        assert adapter.check_gate("cross_examine") is None
        assert adapter.check_gate("consensus") is None

    def test_on_user_action_no_raise(self, adapter):
        adapter.on_user_action("submit", {"user": "test"})

    def test_close_no_raise(self, adapter):
        adapter.close()

    def test_close_idempotent(self, adapter):
        adapter.close()
        adapter.close()  # second close must not raise


# ══════════════════════════════════════════════════════════════════════════
# 3. CompositeAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestCompositeAdapter:
    """Fan-out, isolation, chaining, gating."""

    # ── Fan-out ──────────────────────────────────────────────────────────

    def test_on_cost_fans_out_to_all_adapters(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([a1, a2])
        comp.on_cost("cardiologist", 0.05, "cross_examine")
        a1.on_cost.assert_called_once_with("cardiologist", 0.05, "cross_examine")
        a2.on_cost.assert_called_once_with("cardiologist", 0.05, "cross_examine")

    def test_on_workflow_start_fans_out(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([a1, a2])
        comp.on_workflow_start("consult", "topic")
        a1.on_workflow_start.assert_called_once_with("consult", "topic")
        a2.on_workflow_start.assert_called_once_with("consult", "topic")

    def test_on_cross_exam_logged_fans_out(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([a1, a2])
        comp.on_cross_exam_logged("topic", {"score": 0.9})
        a1.on_cross_exam_logged.assert_called_once()
        a2.on_cross_exam_logged.assert_called_once()

    # ── Isolation ────────────────────────────────────────────────────────

    def test_raising_adapter_does_not_stop_others(self):
        """If one sub-adapter raises on_cost, the rest still execute."""
        good = MagicMock(spec=_FullAdapter)
        bad = _RaisingAdapter()
        comp = CompositeAdapter([bad, good])
        comp.on_cost("cardiologist", 0.01, "cross_examine")
        good.on_cost.assert_called_once()

    def test_raising_adapter_increments_error_count(self):
        bad = _RaisingAdapter()
        comp = CompositeAdapter([bad])
        comp.on_cost("cardiologist", 0.01, "cross_examine")
        assert comp._error_counts.get("_RaisingAdapter", 0) >= 1

    def test_multiple_raises_accumulate_counts(self):
        bad = _RaisingAdapter()
        comp = CompositeAdapter([bad])
        comp.on_cost("c", 0.01, "op")
        comp.on_cost("c", 0.01, "op")
        assert comp._error_counts.get("_RaisingAdapter", 0) >= 2

    def test_fail_fast_mode_propagates_first_error(self):
        bad = _RaisingAdapter()
        good = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([bad, good], fail_fast=True)
        with pytest.raises(RuntimeError, match="on_cost explosion"):
            comp.on_cost("c", 0.01, "op")
        # good was NOT called because fail_fast stopped iteration
        good.on_cost.assert_not_called()

    # ── enrich_topic chaining ────────────────────────────────────────────

    def test_enrich_topic_chains_sequentially(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        a1.enrich_topic.return_value = "enriched by a1"
        a2.enrich_topic.return_value = "enriched by a2"
        comp = CompositeAdapter([a1, a2])
        result = comp.enrich_topic("original", "cross_examine")
        # a1 gets original, a2 gets a1's output
        a1.enrich_topic.assert_called_once_with("original", "cross_examine")
        a2.enrich_topic.assert_called_once_with("enriched by a1", "cross_examine")
        assert result == "enriched by a2"

    def test_enrich_topic_skips_failed_adapter_continues_chain(self):
        bad = _RaisingAdapter()
        good = MagicMock(spec=_FullAdapter)
        good.enrich_topic.return_value = "good enrichment"
        comp = CompositeAdapter([bad, good])
        result = comp.enrich_topic("original", "cross_examine")
        # bad raised, chain continues with unenriched topic fed to good
        good.enrich_topic.assert_called_once_with("original", "cross_examine")
        assert result == "good enrichment"

    # ── check_gate ───────────────────────────────────────────────────────

    def test_check_gate_block_mode_raises_on_first_block(self):
        blocking = _BlockingAdapter()
        good = MagicMock(spec=_FullAdapter)
        good.check_gate.return_value = None
        comp = CompositeAdapter([blocking, good], gate_mode="block")
        with pytest.raises(GateBlockedError, match="blocked by test"):
            comp.check_gate("cross_examine")

    def test_check_gate_block_mode_passes_when_no_blocks(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        a1.check_gate.return_value = None
        a2.check_gate.return_value = None
        comp = CompositeAdapter([a1, a2], gate_mode="block")
        result = comp.check_gate("cross_examine")
        assert result is None

    def test_check_gate_warn_mode_returns_reason_without_raising(self):
        blocking = _BlockingAdapter()
        comp = CompositeAdapter([blocking], gate_mode="warn")
        result = comp.check_gate("cross_examine")
        assert result == "blocked by test"

    def test_check_gate_raising_adapter_does_not_block_gate(self):
        """A check_gate that raises (not GateBlockedError) is caught, chain continues."""
        bad = _RaisingAdapter()
        comp = CompositeAdapter([bad], gate_mode="block")
        result = comp.check_gate("cross_examine")
        assert result is None  # exception swallowed, not a gate block

    # ── capabilities union ───────────────────────────────────────────────

    def test_capabilities_unions_all_adapters(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        a1.capabilities = Capability.COST_TELEMETRY
        a2.capabilities = Capability.GIT_CONTEXT
        comp = CompositeAdapter([a1, a2])
        caps = comp.capabilities
        assert Capability.COST_TELEMETRY in caps
        assert Capability.GIT_CONTEXT in caps

    # ── thread_safe ──────────────────────────────────────────────────────

    def test_thread_safe_true_when_all_true(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        a1.thread_safe = True
        a2.thread_safe = True
        comp = CompositeAdapter([a1, a2])
        assert comp.thread_safe is True

    def test_thread_safe_false_when_any_false(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        a1.thread_safe = True
        a2.thread_safe = False
        comp = CompositeAdapter([a1, a2])
        assert comp.thread_safe is False

    # ── close ────────────────────────────────────────────────────────────

    def test_close_calls_all_adapters(self):
        a1 = MagicMock(spec=_FullAdapter)
        a2 = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([a1, a2])
        comp.close()
        a1.close.assert_called_once()
        a2.close.assert_called_once()

    def test_close_continues_after_one_adapter_raises(self):
        failing = MagicMock(spec=_FullAdapter)
        failing.close.side_effect = RuntimeError("close failed")
        good = MagicMock(spec=_FullAdapter)
        comp = CompositeAdapter([failing, good])
        comp.close()  # must not raise
        good.close.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# 4. RedisAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestRedisAdapter:
    """Redis telemetry writes — mocked client, no live Redis required."""

    @pytest.fixture
    def mock_redis_module(self):
        """Patch the redis package import used inside RedisAdapter.__init__."""
        mock_redis = MagicMock()
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_redis.Redis.return_value = mock_client
        return mock_redis, mock_client, mock_pipe

    @pytest.fixture
    def adapter_and_client(self, mock_redis_module):
        mock_redis, mock_client, mock_pipe = mock_redis_module
        with patch.dict("sys.modules", {"redis": mock_redis}):
            from three_surgeons.adapters._redis import RedisAdapter
            adapter = RedisAdapter()
        return adapter, mock_client, mock_pipe

    def test_capabilities_include_cost_and_evidence(self, adapter_and_client):
        adapter, _, _ = adapter_and_client
        caps = adapter.capabilities
        assert Capability.COST_TELEMETRY in caps
        assert Capability.EVIDENCE_MIRROR in caps

    def test_thread_safe_is_true(self, adapter_and_client):
        adapter, _, _ = adapter_and_client
        assert adapter.thread_safe is True

    def test_on_cost_calls_pipeline(self, adapter_and_client):
        adapter, client, pipe = adapter_and_client
        adapter.on_cost("cardiologist", 0.05, "cross_examine")
        # pipeline was created and executed
        client.pipeline.assert_called_once()
        pipe.execute.assert_called_once()

    def test_on_cost_uses_hincrbyfloat_with_surgeon_key(self, adapter_and_client):
        adapter, client, pipe = adapter_and_client
        adapter.on_cost("cardiologist", 0.05, "cross_examine")
        # First hincrbyfloat call should include surgeon name
        calls = pipe.hincrbyfloat.call_args_list
        assert len(calls) >= 1
        # surgeon key in first call
        assert calls[0][0][1] == "cardiologist"
        assert calls[0][0][2] == 0.05

    def test_on_cost_also_increments_total(self, adapter_and_client):
        adapter, client, pipe = adapter_and_client
        adapter.on_cost("cardiologist", 0.05, "cross_examine")
        calls = pipe.hincrbyfloat.call_args_list
        keys = [c[0][1] for c in calls]
        assert "total" in keys

    def test_on_cross_exam_logged_calls_lpush(self, adapter_and_client):
        adapter, client, pipe = adapter_and_client
        adapter.on_cross_exam_logged("test topic", {"score": 0.9})
        pipe.lpush.assert_called_once()
        args = pipe.lpush.call_args[0]
        assert args[0] == "surgeons:cross_exam_results"

    def test_on_cross_exam_logged_caps_list_at_50(self, adapter_and_client):
        adapter, client, pipe = adapter_and_client
        adapter.on_cross_exam_logged("test topic", {})
        pipe.ltrim.assert_called_once_with("surgeons:cross_exam_results", 0, 49)

    def test_on_error_calls_hincrby(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        adapter.on_error("cross_examine", RuntimeError("boom"), {})
        client.hincrby.assert_called_once_with("surgeons:errors", "cross_examine", 1)

    def test_on_error_does_not_raise_when_redis_fails(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        client.hincrby.side_effect = ConnectionError("Redis down")
        # on_error must NEVER raise — Zero Silent Failures means we log, not crash
        adapter.on_error("cross_examine", RuntimeError("original"), {})

    def test_on_workflow_start_sets_key_with_ttl(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        adapter.on_workflow_start("cross_examine", "some topic")
        client.setex.assert_called_once()
        args = client.setex.call_args[0]
        assert args[0] == "surgeons:workflow_active"
        assert args[1] == 300

    def test_on_workflow_start_does_not_raise_on_redis_failure(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        client.setex.side_effect = ConnectionError("down")
        adapter.on_workflow_start("op", "topic")

    def test_on_workflow_end_deletes_active_key(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        adapter.on_workflow_end("cross_examine", "topic", {})
        client.delete.assert_called_once_with("surgeons:workflow_active")

    def test_enrich_topic_returns_unchanged(self, adapter_and_client):
        adapter, _, _ = adapter_and_client
        assert adapter.enrich_topic("my topic", "op") == "my topic"

    def test_check_gate_returns_none(self, adapter_and_client):
        adapter, _, _ = adapter_and_client
        assert adapter.check_gate("op") is None

    def test_close_calls_redis_close(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        adapter.close()
        client.close.assert_called_once()

    def test_close_does_not_raise_if_redis_close_fails(self, adapter_and_client):
        adapter, client, _ = adapter_and_client
        client.close.side_effect = RuntimeError("close failed")
        adapter.close()


# ══════════════════════════════════════════════════════════════════════════
# 5. GitAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestGitAdapter:
    """Topic enrichment with git context — subprocess mocked."""

    @pytest.fixture
    def adapter(self):
        from three_surgeons.adapters._git import GitAdapter
        return GitAdapter(max_commits=3)

    def test_capabilities_include_git_context(self, adapter):
        assert Capability.GIT_CONTEXT in adapter.capabilities

    def test_thread_safe_is_true(self, adapter):
        assert adapter.thread_safe is True

    def test_enrich_topic_non_cross_exam_op_returns_unchanged(self, adapter):
        result = adapter.enrich_topic("my topic", "probe")
        assert result == "my topic"

    def test_enrich_topic_consensus_op_returns_unchanged_when_no_git(self, adapter):
        """When subprocess raises (no git), topic returned unchanged."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = adapter.enrich_topic("my topic", "consensus")
        assert result == "my topic"

    def test_enrich_topic_cross_examine_appends_git_context(self, adapter):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234 some commit\ndef5678 another commit"
        with patch("subprocess.run", return_value=mock_result):
            result = adapter.enrich_topic("original topic", "cross_examine")
        assert "original topic" in result
        assert "Git Context" in result or "git" in result.lower()

    def test_enrich_topic_consult_op_enriched(self, adapter):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234 commit msg"
        with patch("subprocess.run", return_value=mock_result):
            result = adapter.enrich_topic("consult topic", "consult")
        assert "consult topic" in result

    def test_enrich_topic_git_returncode_nonzero_returns_unchanged(self, adapter):
        mock_result = MagicMock()
        mock_result.returncode = 128  # not a git repo
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            result = adapter.enrich_topic("topic", "cross_examine")
        assert result == "topic"

    def test_enrich_topic_timeout_returns_unchanged(self, adapter):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 3)):
            result = adapter.enrich_topic("topic", "cross_examine")
        assert result == "topic"

    def test_enrich_topic_returns_string(self, adapter):
        with patch("subprocess.run", side_effect=OSError("no git")):
            result = adapter.enrich_topic("topic", "cross_examine")
        assert isinstance(result, str)

    def test_check_gate_returns_none(self, adapter):
        assert adapter.check_gate("cross_examine") is None

    def test_non_lifecycle_hooks_no_raise(self, adapter):
        adapter.on_init()
        adapter.on_workflow_start("op", "topic")
        adapter.on_workflow_end("op", "topic", {})
        adapter.on_cost("surgeon", 0.01, "op")
        adapter.on_cross_exam_logged("topic", {})
        adapter.on_error("op", ValueError("e"), {})
        adapter.on_user_action("action", {})
        adapter.close()


# ══════════════════════════════════════════════════════════════════════════
# 6. ContextDNAAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestContextDNAAdapter:
    """HTTP calls mocked via urllib.request.urlopen patch."""

    @pytest.fixture(autouse=True)
    def reset_error_counts(self):
        """Reset module-level error counter before each test."""
        import three_surgeons.adapters._contextdna as mod
        mod._error_counts.clear()
        yield
        mod._error_counts.clear()

    @pytest.fixture
    def adapter(self):
        from three_surgeons.adapters._contextdna import ContextDNAAdapter
        return ContextDNAAdapter()

    def _make_200_response(self):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_capabilities_include_evidence_and_critical(self, adapter):
        caps = adapter.capabilities
        assert Capability.EVIDENCE_MIRROR in caps
        assert Capability.CRITICAL_FINDINGS in caps
        assert Capability.GAINS_GATE in caps

    def test_on_cost_posts_to_finding_endpoint(self, adapter):
        resp = self._make_200_response()
        with patch("urllib.request.urlopen", return_value=resp) as mock_urlopen:
            adapter.on_cost("cardiologist", 0.05, "cross_examine")
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert "finding" in req.full_url

    def test_on_cross_exam_logged_posts_finding(self, adapter):
        resp = self._make_200_response()
        with patch("urllib.request.urlopen", return_value=resp) as mock_urlopen:
            adapter.on_cross_exam_logged("test topic", {"score": 0.9})
        mock_urlopen.assert_called_once()

    def test_on_error_posts_finding(self, adapter):
        resp = self._make_200_response()
        with patch("urllib.request.urlopen", return_value=resp) as mock_urlopen:
            adapter.on_error("cross_examine", RuntimeError("boom"), {"ctx": "x"})
        mock_urlopen.assert_called_once()

    def test_on_cost_http_failure_increments_error_counter(self, adapter):
        import three_surgeons.adapters._contextdna as mod
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("refused")):
            adapter.on_cost("cardiologist", 0.05, "cross_examine")
        assert mod._error_counts.get("ContextDNAAdapter", 0) >= 1

    def test_on_cost_http_failure_does_not_raise(self, adapter):
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("refused")):
            adapter.on_cost("cardiologist", 0.05, "op")  # must not raise

    def test_on_cross_exam_logged_http_failure_does_not_raise(self, adapter):
        with patch("urllib.request.urlopen",
                   side_effect=OSError("network error")):
            adapter.on_cross_exam_logged("topic", {})

    def test_check_gate_returns_none_when_service_reachable(self, adapter):
        resp = self._make_200_response()
        with patch("urllib.request.urlopen", return_value=resp):
            result = adapter.check_gate()
        assert result is None

    def test_check_gate_returns_string_when_service_unreachable(self, adapter):
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("refused")):
            result = adapter.check_gate()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_check_gate_returns_string_on_non_200(self, adapter):
        resp = MagicMock()
        resp.status = 503
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = adapter.check_gate()
        assert isinstance(result, str)

    def test_on_init_does_not_raise_when_service_up(self, adapter):
        resp = self._make_200_response()
        with patch("urllib.request.urlopen", return_value=resp):
            adapter.on_init()

    def test_on_init_does_not_raise_when_service_down(self, adapter):
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("refused")):
            adapter.on_init()  # must not raise

    def test_enrich_topic_returns_unchanged(self, adapter):
        assert adapter.enrich_topic("topic") == "topic"

    def test_close_no_raise(self, adapter):
        adapter.close()

    def test_multiple_failures_accumulate_error_count(self, adapter):
        import three_surgeons.adapters._contextdna as mod
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("down")):
            adapter.on_cost("c", 0.01, "op")
            adapter.on_cost("c", 0.01, "op")
            adapter.on_cost("c", 0.01, "op")
        assert mod._error_counts.get("ContextDNAAdapter", 0) == 3


# ══════════════════════════════════════════════════════════════════════════
# 7. ObservabilityAdapter
# ══════════════════════════════════════════════════════════════════════════


class TestObservabilityAdapter:
    """SQLite writes in a tmp dir — no production db touched."""

    @pytest.fixture(autouse=True)
    def reset_error_counts(self):
        import three_surgeons.adapters._observability as mod
        mod._error_counts.clear()
        yield
        mod._error_counts.clear()

    @pytest.fixture
    def adapter(self, tmp_path):
        from three_surgeons.adapters._observability import ObservabilityAdapter
        import three_surgeons.adapters._observability as mod
        # Redirect db path to tmp_path
        db_dir = str(tmp_path / ".3surgeons")
        db_path = str(tmp_path / ".3surgeons" / "observability.db")
        with patch.object(mod, "_DB_DIR", db_dir), \
             patch.object(mod, "_DB_PATH", db_path):
            a = ObservabilityAdapter()
            a.on_init()
            yield a
            a.close()

    def test_capabilities_include_observability(self, adapter):
        assert Capability.OBSERVABILITY in adapter.capabilities

    def test_thread_safe_is_true(self, adapter):
        assert adapter.thread_safe is True

    def test_on_cost_inserts_row(self, adapter):
        adapter.on_cost("cardiologist", 0.05, "cross_examine")
        rows = adapter._conn.execute(
            "SELECT * FROM events WHERE event_type='cost'"
        ).fetchall()
        assert len(rows) == 1

    def test_on_cost_stores_surgeon(self, adapter):
        adapter.on_cost("neurologist", 0.02, "consult")
        row = adapter._conn.execute(
            "SELECT surgeon FROM events WHERE event_type='cost'"
        ).fetchone()
        assert row[0] == "neurologist"

    def test_on_error_inserts_row(self, adapter):
        adapter.on_error("cross_examine", ValueError("fail"), {"ctx": "x"})
        rows = adapter._conn.execute(
            "SELECT * FROM events WHERE event_type='error'"
        ).fetchall()
        assert len(rows) == 1

    def test_on_error_stores_operation(self, adapter):
        adapter.on_error("consult", RuntimeError("e"), {})
        row = adapter._conn.execute(
            "SELECT operation FROM events WHERE event_type='error'"
        ).fetchone()
        assert row[0] == "consult"

    def test_on_cross_exam_logged_inserts_row(self, adapter):
        adapter.on_cross_exam_logged("topic", {"score": 0.9})
        rows = adapter._conn.execute(
            "SELECT * FROM events WHERE event_type='cross_exam'"
        ).fetchall()
        assert len(rows) == 1

    def test_multiple_events_all_stored(self, adapter):
        adapter.on_cost("c", 0.01, "op")
        adapter.on_cost("n", 0.02, "op")
        adapter.on_error("op", ValueError("e"), {})
        count = adapter._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 3

    def test_db_uses_wal_journal_mode(self, adapter):
        mode = adapter._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_close_sets_conn_to_none(self, adapter):
        adapter.close()
        assert adapter._conn is None

    def test_close_idempotent(self, adapter):
        adapter.close()
        adapter.close()  # second close must not raise

    def test_on_cost_after_close_does_not_raise(self, adapter):
        adapter.close()
        adapter.on_cost("c", 0.01, "op")  # _conn is None, should not raise

    def test_check_gate_returns_none(self, adapter):
        assert adapter.check_gate() is None

    def test_enrich_topic_returns_unchanged(self, adapter):
        assert adapter.enrich_topic("my topic") == "my topic"


# ══════════════════════════════════════════════════════════════════════════
# 8. Detection probes + TTL cache
# ══════════════════════════════════════════════════════════════════════════


class TestDetectionAndCache:
    """auto_detect, probe functions, TTL cache behaviour."""

    @pytest.fixture(autouse=True)
    def invalidate_cache(self):
        """Always start each test with a cold cache."""
        from three_surgeons.adapters._detection import _invalidate_probe_cache
        _invalidate_probe_cache()
        yield
        _invalidate_probe_cache()

    def test_auto_detect_returns_standalone_when_all_probes_fail(self):
        """When no infra is reachable, auto_detect returns StandaloneAdapter."""
        from three_surgeons.adapters._detection import auto_detect
        with patch("three_surgeons.adapters._detection._probe_redis",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_git",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_contextdna",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_observability",
                   return_value=False):
            adapter = auto_detect()
        assert isinstance(adapter, StandaloneAdapter)

    def test_auto_detect_returns_composite_when_some_probes_pass(self):
        """When at least one probe succeeds, auto_detect returns CompositeAdapter."""
        from three_surgeons.adapters._detection import auto_detect
        with patch("three_surgeons.adapters._detection._probe_redis",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_git",
                   return_value=True), \
             patch("three_surgeons.adapters._detection._probe_contextdna",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_observability",
                   return_value=False):
            adapter = auto_detect()
        assert isinstance(adapter, CompositeAdapter)

    def test_auto_detect_result_satisfies_protocol(self):
        from three_surgeons.adapters._detection import auto_detect
        with patch("three_surgeons.adapters._detection._probe_redis",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_git",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_contextdna",
                   return_value=False), \
             patch("three_surgeons.adapters._detection._probe_observability",
                   return_value=False):
            adapter = auto_detect()
        assert isinstance(adapter, SurgeryAdapter)

    def test_cache_avoids_re_probe_within_ttl(self):
        """Second call within TTL should not re-invoke probe functions."""
        from three_surgeons.adapters._detection import auto_detect
        probe_git = MagicMock(return_value=False)
        probe_redis = MagicMock(return_value=False)
        probe_cdna = MagicMock(return_value=False)
        probe_obs = MagicMock(return_value=False)
        with patch("three_surgeons.adapters._detection._probe_git", probe_git), \
             patch("three_surgeons.adapters._detection._probe_redis", probe_redis), \
             patch("three_surgeons.adapters._detection._probe_contextdna", probe_cdna), \
             patch("three_surgeons.adapters._detection._probe_observability", probe_obs):
            auto_detect()  # first call — probes run
            auto_detect()  # second call — should use cache
        # Probes should have been called exactly once (cache hit on second call)
        assert probe_git.call_count == 1
        assert probe_redis.call_count == 1

    def test_cache_re_probes_after_ttl_expiry(self):
        """After TTL expires, probes must run again."""
        from three_surgeons.adapters import _detection as det
        from three_surgeons.adapters._detection import auto_detect

        probe_git = MagicMock(return_value=False)
        probe_redis = MagicMock(return_value=False)
        probe_cdna = MagicMock(return_value=False)
        probe_obs = MagicMock(return_value=False)
        with patch("three_surgeons.adapters._detection._probe_git", probe_git), \
             patch("three_surgeons.adapters._detection._probe_redis", probe_redis), \
             patch("three_surgeons.adapters._detection._probe_contextdna", probe_cdna), \
             patch("three_surgeons.adapters._detection._probe_observability", probe_obs):
            # First call
            auto_detect()
            assert probe_git.call_count == 1

            # Manually expire the cache by backdating it
            with det._probe_cache_lock:
                cached_time, cached_adapter = det._probe_cache
                det._probe_cache = (cached_time - det._PROBE_CACHE_TTL - 1.0, cached_adapter)

            # Second call should re-probe
            auto_detect()
            assert probe_git.call_count == 2

    def test_invalidate_probe_cache_forces_re_probe(self):
        from three_surgeons.adapters._detection import auto_detect, _invalidate_probe_cache
        probe_git = MagicMock(return_value=False)
        probe_redis = MagicMock(return_value=False)
        probe_cdna = MagicMock(return_value=False)
        probe_obs = MagicMock(return_value=False)
        with patch("three_surgeons.adapters._detection._probe_git", probe_git), \
             patch("three_surgeons.adapters._detection._probe_redis", probe_redis), \
             patch("three_surgeons.adapters._detection._probe_contextdna", probe_cdna), \
             patch("three_surgeons.adapters._detection._probe_observability", probe_obs):
            auto_detect()
            assert probe_git.call_count == 1
            _invalidate_probe_cache()
            auto_detect()
            assert probe_git.call_count == 2


# ══════════════════════════════════════════════════════════════════════════
# 9. AdapterContext
# ══════════════════════════════════════════════════════════════════════════


class TestAdapterContext:
    """Context manager lifecycle — auto-detect, fallback, close."""

    @pytest.fixture(autouse=True)
    def invalidate_cache(self):
        from three_surgeons.adapters._detection import _invalidate_probe_cache
        _invalidate_probe_cache()
        yield
        _invalidate_probe_cache()

    def _all_probes_false(self):
        return (
            patch("three_surgeons.adapters._detection._probe_redis",
                  return_value=False),
            patch("three_surgeons.adapters._detection._probe_git",
                  return_value=False),
            patch("three_surgeons.adapters._detection._probe_contextdna",
                  return_value=False),
            patch("three_surgeons.adapters._detection._probe_observability",
                  return_value=False),
        )

    def test_context_yields_surgery_adapter(self):
        patches = self._all_probes_false()
        with patches[0], patches[1], patches[2], patches[3]:
            with AdapterContext() as adapter:
                assert isinstance(adapter, SurgeryAdapter)

    def test_context_yields_standalone_when_no_infra(self):
        patches = self._all_probes_false()
        with patches[0], patches[1], patches[2], patches[3]:
            with AdapterContext() as adapter:
                assert isinstance(adapter, StandaloneAdapter)

    def test_context_calls_close_on_exit(self):
        """AdapterContext must call adapter.close() when exiting."""
        mock_adapter = MagicMock(spec=_FullAdapter)
        with patch("three_surgeons.adapters._detection.auto_detect",
                   return_value=mock_adapter):
            with AdapterContext():
                pass
        mock_adapter.close.assert_called_once()

    def test_context_calls_close_even_on_exception(self):
        """close() must be called even when an exception propagates from body."""
        mock_adapter = MagicMock(spec=_FullAdapter)
        with patch("three_surgeons.adapters._detection.auto_detect",
                   return_value=mock_adapter):
            with pytest.raises(ValueError):
                with AdapterContext():
                    raise ValueError("body error")
        mock_adapter.close.assert_called_once()

    def test_context_falls_back_to_standalone_when_auto_detect_raises(self):
        with patch("three_surgeons.adapters._detection.auto_detect",
                   side_effect=RuntimeError("detection failed")):
            with AdapterContext() as adapter:
                assert isinstance(adapter, StandaloneAdapter)

    def test_context_calls_on_init(self):
        mock_adapter = MagicMock(spec=_FullAdapter)
        with patch("three_surgeons.adapters._detection.auto_detect",
                   return_value=mock_adapter):
            with AdapterContext():
                pass
        mock_adapter.on_init.assert_called_once()

    def test_context_does_not_suppress_body_exceptions(self):
        patches = self._all_probes_false()
        with patches[0], patches[1], patches[2], patches[3]:
            with pytest.raises(RuntimeError, match="body error"):
                with AdapterContext():
                    raise RuntimeError("body error")

    def test_get_standalone_returns_standalone_adapter(self):
        adapter = get_standalone()
        assert isinstance(adapter, StandaloneAdapter)
        assert isinstance(adapter, SurgeryAdapter)

    def test_get_standalone_returns_new_instance_each_call(self):
        a1 = get_standalone()
        a2 = get_standalone()
        assert a1 is not a2
