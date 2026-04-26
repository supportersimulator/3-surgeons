"""Confabulation visibility tests (RACE O2).

The detector existed (RACE M2) but flag results lived only in
``CrossExamResult.confabulation_flags`` and a state-backend counter -- both
invisible to subagent / CLI callers that print ``cardiologist_report``,
``neurologist_report``, or ``synthesis``.

These tests pin three guarantees:

  1. A confabulated surgeon answer surfaces an inline warning marker on the
     surgeon's user-facing report string (consult + cross_examine).
  2. A clean answer never gets a marker.
  3. ``3s probe`` displays the per-surgeon confab counter.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from click.testing import CliRunner

from three_surgeons.cli.main import cli
from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


# ── Fixtures ─────────────────────────────────────────────────────────


_KERNEL_PM_HALLUCINATION = (
    "The kernel PM callbacks fire when the syscall hooks dispatch. "
    "The kernel parameter baseline was reset by the PM domain."
)
_CLEAN_WEBHOOK_ANSWER = (
    "The webhook fix corrected the HMAC signature header so the "
    "endpoint returns 200 OK reliably."
)
_WEBHOOK_QUESTION = "Why did the Context DNA webhook fix improve delivery?"

_WARNING_MARKER = "[WARNING] Confabulation flag"


def _make_team(tmp_path, cardio_text: str, neuro_text: str):
    cardio = MagicMock()
    cardio.query.return_value = LLMResponse(
        ok=True,
        content=cardio_text,
        latency_ms=100,
        model="gpt-4.1-mini",
        cost_usd=0.001,
    )
    neuro = MagicMock()
    neuro.query.return_value = LLMResponse(
        ok=True,
        content=neuro_text,
        latency_ms=50,
        model="qwen3:4b",
    )
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    state = MemoryBackend()
    team = SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=state,
    )
    return team, state


# ── Inline warning marker on surgeon report ──────────────────────────


class TestConsultMarker:
    """``consult()`` must surface the flag inside ``*_report`` strings."""

    def test_confabulated_cardio_gets_marker(self, tmp_path):
        team, _ = _make_team(
            tmp_path,
            cardio_text=_KERNEL_PM_HALLUCINATION,
            neuro_text=_CLEAN_WEBHOOK_ANSWER,
        )

        result = team.consult(_WEBHOOK_QUESTION)

        # The confabulated answer keeps its body AND gains the marker.
        assert result.cardiologist_report is not None
        assert _KERNEL_PM_HALLUCINATION in result.cardiologist_report
        assert _WARNING_MARKER in result.cardiologist_report

        # The clean answer is untouched.
        assert result.neurologist_report == _CLEAN_WEBHOOK_ANSWER
        assert _WARNING_MARKER not in (result.neurologist_report or "")

    def test_clean_answers_have_no_marker(self, tmp_path):
        team, _ = _make_team(
            tmp_path,
            cardio_text=_CLEAN_WEBHOOK_ANSWER,
            neuro_text=_CLEAN_WEBHOOK_ANSWER,
        )

        result = team.consult(_WEBHOOK_QUESTION)

        assert _WARNING_MARKER not in (result.cardiologist_report or "")
        assert _WARNING_MARKER not in (result.neurologist_report or "")
        assert result.confabulation_flags == {}

    def test_marker_includes_signal_detail(self, tmp_path):
        """Marker must show signals so reviewers can triage quickly."""
        team, _ = _make_team(
            tmp_path,
            cardio_text=_KERNEL_PM_HALLUCINATION,
            neuro_text=_CLEAN_WEBHOOK_ANSWER,
        )
        result = team.consult(_WEBHOOK_QUESTION)
        assert "out_of_domain:kernel" in (result.cardiologist_report or "") \
            or "fabricated_jargon:" in (result.cardiologist_report or "")
        assert "confidence=" in (result.cardiologist_report or "")


# ── cross_examine: synthesis banner + report markers ─────────────────


class TestCrossExamineMarker:
    """``cross_examine()`` must surface the flag and warn in synthesis."""

    def test_confabulated_cardio_gets_marker_and_synthesis_banner(self, tmp_path):
        team, _ = _make_team(
            tmp_path,
            cardio_text=_KERNEL_PM_HALLUCINATION,
            neuro_text=_CLEAN_WEBHOOK_ANSWER,
        )

        result = team.cross_examine(_WEBHOOK_QUESTION)

        # Marker on the cardiologist report.
        assert _WARNING_MARKER in (result.cardiologist_report or "")
        # Synthesis banner names the flagged surgeon.
        if result.synthesis:
            assert _WARNING_MARKER in result.synthesis
            assert "cardiologist" in result.synthesis.lower()

    def test_cross_examine_clean_no_marker(self, tmp_path):
        team, _ = _make_team(
            tmp_path,
            cardio_text=_CLEAN_WEBHOOK_ANSWER,
            neuro_text=_CLEAN_WEBHOOK_ANSWER,
        )
        result = team.cross_examine(_WEBHOOK_QUESTION)
        assert _WARNING_MARKER not in (result.cardiologist_report or "")
        assert _WARNING_MARKER not in (result.neurologist_report or "")
        if result.synthesis:
            assert _WARNING_MARKER not in result.synthesis


# ── probe shows confab counter ───────────────────────────────────────


class TestProbeShowsCounter:
    """``3s probe`` output must surface confab counts.

    We can't easily reach a remote LLM in tests, so we exercise the probe
    command via Click's runner -- the surgeon health line will FAIL because
    no endpoint is reachable, but the per-surgeon confab counter and the
    cumulative line must still appear.
    """

    def test_probe_renders_confab_counter(self, tmp_path, monkeypatch):
        # Pre-populate the state backend that probe reads from. We need probe
        # to instantiate a NEW backend with the same config and observe the
        # same data, so we use a SQLite backend on disk.
        from three_surgeons.core.state import create_backend, SQLiteBackend

        db_path = tmp_path / "state.db"
        backend = create_backend("sqlite", db_path=str(db_path))
        assert isinstance(backend, SQLiteBackend)
        backend.increment("confab:by_surgeon:cardiologist")
        backend.increment("confab:by_surgeon:cardiologist")
        backend.increment("confab:by_surgeon:cardiologist")
        backend.increment("confab:total_flagged")
        backend.increment("confab:total_flagged")
        backend.increment("confab:total_flagged")

        # Patch create_backend_from_config in the CLI module to return our
        # pre-populated backend so probe sees the seeded counters. (Import
        # the module by its full dotted path -- ``three_surgeons.cli`` re-
        # exports a ``main`` function, which would shadow the module.)
        import importlib

        cli_main_mod = importlib.import_module("three_surgeons.cli.main")

        def _fake_factory(_state_config):
            return backend

        monkeypatch.setattr(cli_main_mod, "create_backend_from_config", _fake_factory)

        runner = CliRunner()
        result = runner.invoke(cli, ["probe"])

        # Probe will exit non-zero because there is no real LLM endpoint
        # available in the test environment. That's fine -- we just need the
        # confab markers on stdout.
        assert "[confab flags: 3]" in result.output, result.output
        assert "[confab flags: 0]" in result.output, result.output
        assert "Confabulation flags (cumulative): total=3" in result.output, result.output
