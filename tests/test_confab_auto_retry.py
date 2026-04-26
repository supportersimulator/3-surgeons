"""Auto-retry on confabulation (RACE R2).

When the confabulation detector flags a surgeon's first answer, the team
should retry the LLM call ONCE with a stricter system prompt that names
the offending signals. The cleaner retry replaces the confabulated draft;
if the retry still confabulates, the original answer is kept and a
WARNING marker is attached so the caller cannot miss the regression.

These tests pin five guarantees:

  1. Clean first-call answers are returned untouched (no retry, no counter
     bump).
  2. A confabulated first call triggers a retry and the retry's clean
     answer is what the caller receives.
  3. When BOTH the first call and the retry confabulate, the original
     answer is returned with a WARNING marker so reviewers can triage.
  4. The auto-retry counters (`confab:auto_retries_attempted/successful/
     still_failed`) increment correctly across all three branches.
  5. Auto-retry never fires more than once per surgeon per call (no
     infinite loop).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


# ── Fixtures ─────────────────────────────────────────────────────────


_KERNEL_PM_HALLUCINATION = (
    "The kernel PM callbacks fire when the syscall hooks dispatch. "
    "The kernel parameter baseline was reset by the PM domain."
)
_SECOND_KERNEL_HALLUCINATION = (
    "Per the Linux kernel docs, the kernel PM callbacks via module_param() "
    "still control the syscall hooks. The kernel parameter baseline persists."
)
_CLEAN_WEBHOOK_ANSWER = (
    "The webhook fix corrected the HMAC signature header so the "
    "endpoint returns 200 OK reliably."
)
_ALSO_CLEAN_WEBHOOK_ANSWER = (
    "The webhook now signs the payload with HMAC and the endpoint "
    "responds 200 OK after the retry policy was tightened."
)
_WEBHOOK_QUESTION = "Why did the Context DNA webhook fix improve delivery?"

_WARNING_MARKER = "[WARNING] Confabulation flag"
_AVOID_PREFIX = "AVOID the following confabulation patterns"


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        ok=True,
        content=content,
        latency_ms=10,
        model="gpt-4.1-mini",
        cost_usd=0.001,
    )


def _make_team(tmp_path, cardio_responses, neuro_responses):
    """cardio_responses / neuro_responses are LISTS — one LLMResponse per call."""
    cardio = MagicMock()
    cardio.query.side_effect = cardio_responses
    neuro = MagicMock()
    neuro.query.side_effect = neuro_responses
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    state = MemoryBackend()
    team = SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=state,
    )
    return team, state, cardio, neuro


def _state_count(state: MemoryBackend, key: str) -> int:
    raw = state.get(key)
    return int(raw) if raw is not None else 0


# ── 1. Clean first call: no retry, no counter bump ──────────────────


class TestCleanFirstCall:
    def test_clean_answer_no_retry_no_counter(self, tmp_path):
        team, state, cardio, neuro = _make_team(
            tmp_path,
            cardio_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
            neuro_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
        )

        result = team.consult(_WEBHOOK_QUESTION)

        assert result.cardiologist_report == _CLEAN_WEBHOOK_ANSWER
        assert result.neurologist_report == _CLEAN_WEBHOOK_ANSWER
        assert _WARNING_MARKER not in (result.cardiologist_report or "")
        assert result.confabulation_flags == {}

        # Exactly one call per surgeon — no retry.
        assert cardio.query.call_count == 1
        assert neuro.query.call_count == 1

        # Counters all zero.
        assert _state_count(state, "confab:auto_retries_attempted") == 0
        assert _state_count(state, "confab:auto_retries_successful") == 0
        assert _state_count(state, "confab:auto_retries_still_failed") == 0
        assert _state_count(state, "confab:total_flagged") == 0


# ── 2. Confab on first call → retry produces clean answer ───────────


class TestRetryProducesClean:
    def test_confab_then_clean_replaces_text(self, tmp_path):
        # Cardio: hallucinates first, retries clean.
        # Neuro: clean on first call (no retry).
        team, state, cardio, neuro = _make_team(
            tmp_path,
            cardio_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_CLEAN_WEBHOOK_ANSWER),
            ],
            neuro_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
        )

        result = team.consult(_WEBHOOK_QUESTION)

        # Cardiologist text must be the CLEAN retry, not the kernel hallucination.
        assert result.cardiologist_report == _CLEAN_WEBHOOK_ANSWER
        assert _KERNEL_PM_HALLUCINATION not in (result.cardiologist_report or "")
        assert _WARNING_MARKER not in (result.cardiologist_report or "")
        # And no surviving flag.
        assert "cardiologist" not in result.confabulation_flags

        # Cardio called twice (initial + retry); neuro called once.
        assert cardio.query.call_count == 2
        assert neuro.query.call_count == 1

        # Counter state: attempted+successful=1, still_failed=0,
        # AND no contribution to the regression dashboard counter.
        assert _state_count(state, "confab:auto_retries_attempted") == 1
        assert _state_count(state, "confab:auto_retries_successful") == 1
        assert _state_count(state, "confab:auto_retries_still_failed") == 0
        assert _state_count(state, "confab:total_flagged") == 0
        assert _state_count(state, "confab:by_surgeon:cardiologist") == 0

    def test_retry_system_prompt_lists_signals(self, tmp_path):
        """The retry must use a stricter system prompt naming the signals."""
        team, _, cardio, _ = _make_team(
            tmp_path,
            cardio_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_CLEAN_WEBHOOK_ANSWER),
            ],
            neuro_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
        )

        team.consult(_WEBHOOK_QUESTION)

        # Second cardio call's `system` kwarg must start with the AVOID directive.
        retry_call = cardio.query.call_args_list[1]
        retry_system = retry_call.kwargs.get("system") or retry_call.args[0]
        assert retry_system.startswith(_AVOID_PREFIX), retry_system[:200]
        # And it must reference at least one detector signal.
        assert (
            "out_of_domain:kernel" in retry_system
            or "fabricated_jargon" in retry_system
        ), retry_system[:400]


# ── 3. Retry still confab → return original + WARNING marker ────────


class TestRetryStillConfab:
    def test_persistent_confab_keeps_original_with_marker(self, tmp_path):
        team, state, cardio, neuro = _make_team(
            tmp_path,
            cardio_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_SECOND_KERNEL_HALLUCINATION),
            ],
            neuro_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
        )

        result = team.consult(_WEBHOOK_QUESTION)

        # Original answer (NOT retry) is preserved so reviewers see the
        # baseline confab — and a marker is attached.
        assert result.cardiologist_report is not None
        assert _KERNEL_PM_HALLUCINATION in result.cardiologist_report
        assert _WARNING_MARKER in result.cardiologist_report
        assert "cardiologist" in result.confabulation_flags

        # Retry happened, but did not help.
        assert cardio.query.call_count == 2

        # Counter state: attempted+still_failed=1, successful=0.
        # AND the regression dashboard counter DID bump (final answer is bad).
        assert _state_count(state, "confab:auto_retries_attempted") == 1
        assert _state_count(state, "confab:auto_retries_successful") == 0
        assert _state_count(state, "confab:auto_retries_still_failed") == 1
        assert _state_count(state, "confab:total_flagged") == 1
        assert _state_count(state, "confab:by_surgeon:cardiologist") == 1


# ── 4. Counter sanity across mixed scenario ──────────────────────────


class TestCounterIncrements:
    def test_one_surgeon_recovers_other_persists(self, tmp_path):
        """Cardio recovers via retry; neuro confabulates twice."""
        team, state, cardio, neuro = _make_team(
            tmp_path,
            cardio_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_CLEAN_WEBHOOK_ANSWER),
            ],
            neuro_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_SECOND_KERNEL_HALLUCINATION),
            ],
        )

        result = team.consult(_WEBHOOK_QUESTION)

        # Cardio: clean retry wins, no surviving flag.
        assert result.cardiologist_report == _CLEAN_WEBHOOK_ANSWER
        assert "cardiologist" not in result.confabulation_flags

        # Neuro: original kept + marker.
        assert _KERNEL_PM_HALLUCINATION in (result.neurologist_report or "")
        assert _WARNING_MARKER in (result.neurologist_report or "")
        assert "neurologist" in result.confabulation_flags

        # Both surgeons retried exactly once.
        assert cardio.query.call_count == 2
        assert neuro.query.call_count == 2

        # Counter aggregation across both surgeons.
        assert _state_count(state, "confab:auto_retries_attempted") == 2
        assert _state_count(state, "confab:auto_retries_successful") == 1
        assert _state_count(state, "confab:auto_retries_still_failed") == 1
        # Only the persistent neuro contributes to the regression dashboard.
        assert _state_count(state, "confab:total_flagged") == 1
        assert _state_count(state, "confab:by_surgeon:neurologist") == 1
        assert _state_count(state, "confab:by_surgeon:cardiologist") == 0


# ── 5. No infinite loop ──────────────────────────────────────────────


class TestNoInfiniteLoop:
    def test_persistent_confab_makes_at_most_two_calls(self, tmp_path):
        """Even if the surgeon would confabulate forever, we stop after one retry."""
        # Provide three distinct confabulated responses; the team must only
        # consume the first two (initial + one retry) and ignore the third.
        team, _, cardio, neuro = _make_team(
            tmp_path,
            cardio_responses=[
                _resp(_KERNEL_PM_HALLUCINATION),
                _resp(_SECOND_KERNEL_HALLUCINATION),
                _resp("a third hallucination that must not be reached"),
            ],
            neuro_responses=[_resp(_CLEAN_WEBHOOK_ANSWER)],
        )

        team.consult(_WEBHOOK_QUESTION)

        assert cardio.query.call_count == 2  # not 3
