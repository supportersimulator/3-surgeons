"""Regression tests for RACE Q2 expanded confabulation patterns.

Real surgeon sessions surfaced a class of hallucinations beyond the kernel/PM
regressions covered by RACE M2:

  - Fictional infrastructure terms ("ghost agents", "ghost subscriptions")
  - Made-up dependency chains ("rollback paradox", "cross-contamination chain")
  - Spurious version pins ("pre-2.10 bug", "post-3.0 release")
  - Fabricated bare references ("per the spec")
  - Out-of-domain noise from new ontologies (orchestration, fleet, NATS,
    election)
  - "the kernel" reaching when the question is plainly userspace

Each new pattern has both a positive trigger test and a false-positive guard
asserting that legitimate use of the same vocabulary stays clean.
"""
from __future__ import annotations

import pytest

from three_surgeons.core.confabulation_detector import (
    detect_confabulation,
    known_domains,
)


# ── New domain ontologies ────────────────────────────────────────────


class TestNewDomains:
    def test_known_domains_includes_q2_additions(self):
        domains = set(known_domains())
        for d in ("orchestration", "fleet", "nats", "election"):
            assert d in domains, f"missing domain: {d}"

    def test_fleet_question_kernel_answer_is_flagged(self):
        question = "Why did the fleet daemon stop receiving fleet-msg pings?"
        answer = (
            "The kernel PM callbacks deferred the syscall hooks so the "
            "kthread scheduler stalled."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is True
        assert any(s.startswith("out_of_domain:kernel") for s in report.signals)

    def test_nats_question_with_nats_answer_is_clean(self):
        question = "How does the NATS subscription handle JetStream replay?"
        answer = (
            "The NATS subscription replays from the JetStream durable "
            "consumer's last ack offset, so the subject hierarchy is "
            "preserved."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is False
        assert not any(s.startswith("out_of_domain:") for s in report.signals)

    def test_election_question_with_unrelated_kernel_answer_is_flagged(self):
        question = "How does our leader election handle a split brain?"
        answer = (
            "The fix re-registers the kernel PM callbacks so the kthread "
            "scheduler doesn't lose its kernel parameter baseline."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is True
        assert any(s.startswith("out_of_domain:kernel") for s in report.signals)

    def test_orchestration_question_with_orchestration_answer_is_clean(self):
        question = "How does the agent pool dispatch subagent tasks?"
        answer = (
            "The agent pool uses a worker pool to dispatch each subagent "
            "via the scheduler's task queue."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is False


# ── Fictional infrastructure terms ───────────────────────────────────


class TestGhostJargon:
    @pytest.mark.parametrize(
        "phrase",
        [
            "The ghost agents kept retrying after the daemon died.",
            "We saw a ghost subscription left over from the previous lease.",
            "A ghost process held the port open for ten minutes.",
        ],
    )
    def test_ghost_phrases_trigger(self, phrase):
        question = "Why is the fleet daemon flapping?"
        report = detect_confabulation(question, phrase)
        assert any(
            s.startswith("fabricated_jargon:ghost ") for s in report.signals
        ), report.signals

    def test_legitimate_ghost_in_question_does_not_double_flag(self):
        # If the QUESTION already uses "ghost subscription", the answer
        # echoing it should not be treated as fabricated.
        question = "What is a ghost subscription in NATS terms?"
        answer = (
            "A ghost subscription is one whose subscriber went away "
            "without unsubscribing cleanly."
        )
        report = detect_confabulation(question, answer)
        assert not any(
            s.startswith("fabricated_jargon:ghost ") for s in report.signals
        )


# ── Made-up dependency chains ────────────────────────────────────────


class TestFabricatedDependencyChains:
    def test_rollback_paradox_triggers(self):
        question = "Why did the deploy revert fail to roll back cleanly?"
        answer = (
            "We hit the rollback paradox: the new schema couldn't be "
            "downgraded without losing rows."
        )
        report = detect_confabulation(question, answer)
        assert any(
            "rollback paradox" in s for s in report.signals
        ), report.signals

    def test_cross_contamination_chain_triggers(self):
        question = "Why did the test run leak state into the next run?"
        answer = (
            "There was a cross-contamination chain through the shared "
            "Redis instance."
        )
        report = detect_confabulation(question, answer)
        assert any(
            "cross-contamination chain" in s or "cross contamination chain" in s
            for s in report.signals
        ), report.signals

    def test_legitimate_rollback_discussion_clean(self):
        # Talking about an ordinary rollback is fine.
        question = "How do we roll back the migration?"
        answer = (
            "Run `alembic downgrade -1` and then redeploy the previous "
            "container tag."
        )
        report = detect_confabulation(question, answer)
        assert not any("paradox" in s for s in report.signals)


# ── Context-sensitive jargon ─────────────────────────────────────────


class TestContextSensitiveJargon:
    def test_circuit_breaker_unexplained_triggers(self):
        # Question never names circuit breakers and the answer wields the
        # term as if pre-known.
        question = "Why are HTTP retries to the downstream API failing?"
        answer = (
            "The circuit breakers tripped, so the downstream calls were "
            "short-circuited."
        )
        report = detect_confabulation(question, answer)
        assert any(
            s == "unexplained_jargon:circuit_breaker" for s in report.signals
        ), report.signals

    def test_circuit_breaker_introduced_with_definition_clean(self):
        question = "How can we protect against repeated downstream failure?"
        answer = (
            "A circuit breaker is a wrapper that fails fast after N "
            "consecutive errors. We can add one in front of the API call."
        )
        report = detect_confabulation(question, answer)
        assert not any(
            "unexplained_jargon" in s for s in report.signals
        ), report.signals

    def test_circuit_breaker_referenced_by_question_clean(self):
        question = "Should we use a circuit breaker around the API call?"
        answer = "Yes, the circuit breakers should wrap the retry loop."
        report = detect_confabulation(question, answer)
        assert not any(
            "unexplained_jargon" in s for s in report.signals
        )

    def test_data_plane_unexplained_triggers(self):
        question = "Why did the routing change break ingress?"
        answer = "The data plane never got the update from the controller."
        report = detect_confabulation(question, answer)
        assert any(
            s == "unexplained_jargon:data_plane" for s in report.signals
        ), report.signals

    def test_control_plane_introduced_clean(self):
        question = "What handles configuration distribution in our service mesh?"
        answer = (
            "The control plane is the component that distributes config to "
            "sidecars."
        )
        report = detect_confabulation(question, answer)
        assert not any(
            "unexplained_jargon" in s for s in report.signals
        )


# ── Spurious version pins ────────────────────────────────────────────


class TestSpuriousVersionPins:
    @pytest.mark.parametrize(
        "phrase",
        [
            "This is a pre-2.10 bug that was patched upstream.",
            "We're hitting a pre-3.4.1 regression in the parser.",
            "After the post-3.0 release the API shape changed.",
            "Post-2.5.0 behavior makes this safer.",
        ],
    )
    def test_version_pin_triggers(self, phrase):
        question = "Why does the CLI parse this argument differently now?"
        report = detect_confabulation(question, phrase)
        assert any(
            s.startswith("fabricated_jargon:") and (
                "pre-" in s or "post-" in s
            )
            for s in report.signals
        ), report.signals

    def test_legitimate_version_reference_clean(self):
        # Plain "Python 3.11" references do not trigger.
        question = "Does our app support Python 3.11?"
        answer = "Yes, we test on Python 3.11 and Python 3.12 in CI."
        report = detect_confabulation(question, answer)
        assert not any(
            s.startswith("fabricated_jargon:") and ("pre-" in s or "post-" in s)
            for s in report.signals
        ), report.signals


# ── Bare unbacked citations ──────────────────────────────────────────


class TestBareCitation:
    @pytest.mark.parametrize(
        "phrase",
        [
            "Per the spec, payloads must be idempotent.",
            "Per the standard, headers should be lowercase.",
            "Per the docs, this flag defaults to true.",
        ],
    )
    def test_bare_citations_trigger(self, phrase):
        question = "Should our handler be idempotent?"
        report = detect_confabulation(question, phrase)
        assert any(
            s.startswith("unbacked_citation:bare_") for s in report.signals
        ), report.signals

    def test_named_citation_in_question_is_clean(self):
        # Question already names the spec, so the answer can refer to it.
        question = "Per the IETF Webhook spec, must payloads be idempotent?"
        answer = "Per the IETF Webhook spec, yes — idempotency is required."
        report = detect_confabulation(question, answer)
        assert not any(
            s.startswith("unbacked_citation:bare_") for s in report.signals
        )


# ── "The kernel" blame in userspace question ─────────────────────────


class TestKernelBlameInUserspace:
    def test_python_question_kernel_blame_triggers(self):
        question = "Why is my Python subprocess hanging on stdin?"
        answer = (
            "The kernel is queuing up the writes and the buffer never "
            "drains."
        )
        report = detect_confabulation(question, answer)
        assert "kernel_blame_in_userspace_question" in report.signals

    def test_webhook_question_kernel_blame_triggers(self):
        question = "Why is the fleet-msg webhook not delivering on retries?"
        answer = "The kernel is dropping the SYN packets before TCP completes."
        report = detect_confabulation(question, answer)
        assert "kernel_blame_in_userspace_question" in report.signals

    def test_kernel_question_kernel_answer_is_clean(self):
        question = "How does the Linux kernel scheduler pick the next kthread?"
        answer = "The kernel picks the highest-priority runnable kthread."
        report = detect_confabulation(question, answer)
        assert "kernel_blame_in_userspace_question" not in report.signals

    def test_userspace_question_no_kernel_blame_clean(self):
        question = "Why is my Python subprocess hanging on stdin?"
        answer = (
            "The child process is waiting on input because stdin was never "
            "closed in the parent. Call proc.stdin.close()."
        )
        report = detect_confabulation(question, answer)
        assert "kernel_blame_in_userspace_question" not in report.signals
