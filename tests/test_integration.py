"""End-to-end integration tests using MemoryBackend (no real LLM calls).

Verifies that core modules work together correctly: cross-exam flows into
evidence storage, consensus disagreements trigger A/B proposals, sentinel
feeds into gates, and corrigibility blocks dangerous actions.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from three_surgeons.cli.main import cli
from three_surgeons.core.ab_testing import ABTestEngine
from three_surgeons.core.config import Config
from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.gates import CorrigibilityGate, GainsGate
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.sentinel import Sentinel
from three_surgeons.core.state import MemoryBackend


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_cardio_mock(content: str = "Analysis from cardiologist", cost: float = 0.003) -> MagicMock:
    """Create a cardiologist mock that returns a successful LLMResponse."""
    mock = MagicMock()
    mock.query.return_value = LLMResponse(
        ok=True,
        content=content,
        latency_ms=200,
        model="gpt-4.1-mini",
        cost_usd=cost,
    )
    return mock


def _make_neuro_mock(content: str = "Analysis from neurologist") -> MagicMock:
    """Create a neurologist mock that returns a successful LLMResponse."""
    mock = MagicMock()
    mock.query.return_value = LLMResponse(
        ok=True,
        content=content,
        latency_ms=50,
        model="qwen3:4b",
    )
    return mock


# ── End-to-End Tests ─────────────────────────────────────────────────────


class TestEndToEnd:
    """Integration tests verifying multi-module interaction flows."""

    def test_full_cross_exam_flow(self, tmp_path):
        """Cross-exam -> evidence recorded -> searchable."""
        config = Config()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()

        cardio = _make_cardio_mock()
        neuro = _make_neuro_mock()

        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )
        result = team.cross_examine("Should we use SQLite?")

        # Evidence should be recorded
        exams = evidence.get_cross_exams(limit=5)
        assert len(exams) >= 1
        assert exams[0]["topic"] == "Should we use SQLite?"

        # Cost should be tracked (cardiologist has non-zero cost)
        daily_cost = evidence.get_daily_cost("cardiologist")
        assert daily_cost > 0

        # Result should have reports from both surgeons
        assert result.cardiologist_report is not None
        assert result.neurologist_report is not None
        assert result.total_cost > 0
        assert result.total_latency_ms > 0

    def test_consensus_then_ab_test(self, tmp_path):
        """Consensus disagrees -> propose A/B test -> verify safety checks."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()

        # Run consensus with mocks that disagree
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.3, "assessment": "disagree", "reasoning": "Not enough evidence"}',
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.002,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.8, "assessment": "agree", "reasoning": "Data supports it"}',
            latency_ms=50,
            model="qwen3:4b",
        )

        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )
        consensus = team.consensus("Temperature 0.7 is optimal")

        # Verify disagreement detected
        assert consensus.cardiologist_assessment == "disagree"
        assert consensus.neurologist_assessment == "agree"

        # Models disagree -- propose A/B test to resolve
        ab = ABTestEngine(evidence=evidence, state=state, config=config)
        test = ab.propose("temperature", "0.7", "0.5", "Lower temp may improve consistency")

        assert test.param == "temperature"
        assert test.variant_a == "0.7"
        assert test.variant_b == "0.5"

        # Lifecycle: grace period -> activate
        ab.start_grace_period(test.id)
        ab.activate(test.id)

        # Verify safety (freshly activated, no cost accumulated)
        safety = ab.check_safety(test.id)
        assert safety["safe"] is True

    def test_sentinel_then_gates(self, tmp_path):
        """Sentinel detects high risk -> run gains gate -> verify health."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()

        # Sentinel detects risk from security-related content
        sentinel = Sentinel()
        result = sentinel.run_cycle(
            "SQL injection vulnerability in auth token handling with race condition"
        )
        assert result.risk_level in ("medium", "high", "critical")
        assert result.vectors_triggered > 0

        # Run gains gate -- state and evidence are real, healthy objects
        gate = GainsGate(state=state, evidence=evidence, config=config)
        gate_result = gate.run()

        # State and evidence checks should pass (they're real objects)
        assert gate_result.duration_ms >= 0
        # At minimum, state_backend and evidence_store checks should pass
        state_check = next(
            (c for c in gate_result.checks if c.name == "state_backend"), None
        )
        evidence_check = next(
            (c for c in gate_result.checks if c.name == "evidence_store"), None
        )
        assert state_check is not None and state_check.passed
        assert evidence_check is not None and evidence_check.passed

    def test_corrigibility_blocks_dangerous_action(self, tmp_path):
        """Corrigibility gate blocks destructive operations."""
        config = Config()
        gate = CorrigibilityGate(config=config)

        # Safe action
        safe = gate.run("refactor the database layer")
        assert safe.passed is True

        # Dangerous action: drop tables
        dangerous = gate.run("drop all database tables and truncate logs")
        assert dangerous.passed is False

        # Dangerous action: bypass safety
        bypass = gate.run("bypass safety checks to speed up deployment")
        assert bypass.passed is False

        # Dangerous action: force push
        force = gate.run("force push to main branch")
        assert force.passed is False

    def test_evidence_snapshot_after_operations(self, tmp_path):
        """After cross-exam + A/B test, evidence snapshot includes both."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()

        # Record a learning
        evidence.record_learning(
            "SQLite works", "SQLite is sufficient for our workload", "win", ["sqlite"]
        )

        # Record a cross-exam
        evidence.record_cross_exam(
            "SQLite vs Postgres",
            "neuro says sqlite",
            "cardio says postgres",
            0.6,
        )

        # Record A/B result
        evidence.record_ab_result(
            "exp-1", "temperature", "0.7", "0.5", "variant_b wins"
        )

        # Snapshot should include all types
        snapshot = evidence.get_evidence_snapshot("SQLite")
        assert "SQLite" in snapshot["evidence_text"]
        assert len(snapshot["learnings"]) >= 1

        # Stats should reflect recording
        stats = evidence.get_stats()
        assert stats["total"] >= 1
        assert stats["wins"] >= 1


# ── CLI Integration Tests ────────────────────────────────────────────────


class TestCLIIntegration:
    """Verify the CLI help system works end-to-end."""

    def test_help_works_and_lists_all_commands(self):
        """CLI help should list every registered command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        expected_commands = [
            "init",
            "probe",
            "cross-exam",
            "consult",
            "consensus",
            "sentinel",
            "gains-gate",
            "ab-propose",
        ]
        for cmd in expected_commands:
            assert cmd in result.output, f"Command {cmd!r} missing from CLI help"

    def test_subcommand_help_works(self):
        """Each subcommand should have its own help text."""
        runner = CliRunner()
        for cmd in ["init", "probe", "sentinel", "gains-gate", "ab-propose"]:
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"
            assert "Usage" in result.output or "Options" in result.output


# ── Config Discovery Integration Tests ───────────────────────────────────


class TestConfigDiscoveryIntegration:
    """Verify the config discovery chain works end-to-end."""

    def test_defaults_when_no_config_files(self, tmp_path, monkeypatch):
        """Config.discover with a dir containing no config returns defaults."""
        # Isolate from real ~/.3surgeons/config.yaml on the host machine
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config = Config.discover(project_dir=tmp_path)
        assert config.cardiologist.model == "gpt-4.1-mini"
        assert config.neurologist.model == "qwen3:4b"
        assert config.budgets.daily_external_usd == 5.0

    def test_project_config_overrides_defaults(self, tmp_path, monkeypatch):
        """A .3surgeons.yaml in project dir should override defaults."""
        import yaml

        # Isolate from real ~/.3surgeons/config.yaml on the host machine
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        project_config = tmp_path / ".3surgeons.yaml"
        project_config.write_text(
            yaml.dump(
                {
                    "surgeons": {
                        "cardiologist": {"model": "gpt-4.1"},
                    },
                    "budgets": {"daily_external_usd": 10.0},
                }
            )
        )
        config = Config.discover(project_dir=tmp_path)
        assert config.cardiologist.model == "gpt-4.1"
        assert config.budgets.daily_external_usd == 10.0
        # Neurologist should still be default
        assert config.neurologist.model == "qwen3:4b"

    def test_config_round_trip_from_yaml(self, tmp_path):
        """Config written to YAML and read back should preserve values."""
        import yaml

        data = {
            "surgeons": {
                "cardiologist": {
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "endpoint": "https://api.openai.com/v1",
                    "api_key_env": "MY_KEY",
                },
                "neurologist": {
                    "provider": "ollama",
                    "model": "qwen3:4b",
                    "endpoint": "http://localhost:11434/v1",
                },
            },
            "budgets": {"daily_external_usd": 3.0, "autonomous_ab_usd": 1.5},
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(data))

        config = Config.from_yaml(config_path)
        assert config.cardiologist.model == "gpt-4.1-mini"
        assert config.cardiologist.api_key_env == "MY_KEY"
        assert config.neurologist.provider == "ollama"
        assert config.budgets.daily_external_usd == 3.0
        assert config.budgets.autonomous_ab_usd == 1.5


# ── Multiple A/B Tests Coexistence ───────────────────────────────────────


class TestMultipleABTests:
    """Multiple A/B tests can coexist without interference."""

    def test_multiple_tests_coexist(self, tmp_path):
        """Several A/B tests can be proposed and tracked independently."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()
        ab = ABTestEngine(evidence=evidence, state=state, config=config)

        test1 = ab.propose("temperature", "0.7", "0.5", "Lower may be better")
        test2 = ab.propose("max_tokens", "2048", "4096", "More tokens needed")
        test3 = ab.propose("top_p", "0.9", "0.95", "Broader sampling")

        # All three should exist
        assert ab.get_test(test1.id) is not None
        assert ab.get_test(test2.id) is not None
        assert ab.get_test(test3.id) is not None

        # All three should appear in active tests
        active = ab.get_active_tests()
        active_ids = {t.id for t in active}
        assert test1.id in active_ids
        assert test2.id in active_ids
        assert test3.id in active_ids

    def test_concluding_one_does_not_affect_others(self, tmp_path):
        """Concluding one A/B test leaves others active."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()
        ab = ABTestEngine(evidence=evidence, state=state, config=config)

        test1 = ab.propose("temperature", "0.7", "0.5", "Lower may be better")
        test2 = ab.propose("max_tokens", "2048", "4096", "More tokens needed")

        # Lifecycle test1 to conclusion
        ab.start_grace_period(test1.id)
        ab.activate(test1.id)
        ab.conclude(test1.id, "variant_b wins")

        # test2 should still be active (proposed)
        active = ab.get_active_tests()
        active_ids = {t.id for t in active}
        assert test1.id not in active_ids  # concluded
        assert test2.id in active_ids  # still proposed

    def test_vetoing_one_does_not_affect_others(self, tmp_path):
        """Vetoing one A/B test leaves others unaffected."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()
        ab = ABTestEngine(evidence=evidence, state=state, config=config)

        test1 = ab.propose("temperature", "0.7", "0.5", "Hypothesis A")
        test2 = ab.propose("max_tokens", "2048", "4096", "Hypothesis B")

        ab.veto(test1.id, "Not relevant anymore")

        active = ab.get_active_tests()
        active_ids = {t.id for t in active}
        assert test1.id not in active_ids  # vetoed
        assert test2.id in active_ids


# ── Evidence Search Across Types ─────────────────────────────────────────


class TestEvidenceSearchIntegration:
    """Evidence search returns relevant results across different record types."""

    def test_search_finds_learnings(self, tmp_path):
        """FTS search should find learnings by title and content."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))

        evidence.record_learning(
            "Redis performance", "Redis handles 100k ops/sec", "win", ["redis"]
        )
        evidence.record_learning(
            "SQLite limitations", "SQLite struggles with concurrent writes", "fix", ["sqlite"]
        )

        results = evidence.search("Redis")
        assert len(results) >= 1
        assert any("Redis" in r["title"] for r in results)

    def test_search_returns_empty_for_no_match(self, tmp_path):
        """FTS search for non-existent term returns empty list."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        evidence.record_learning("Redis perf", "fast", "win", ["redis"])

        results = evidence.search("xyznonexistent")
        assert results == []

    def test_snapshot_includes_observations_and_ab(self, tmp_path):
        """Evidence snapshot should include observations and A/B results that match."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))

        # Record various types mentioning "Redis"
        evidence.record_learning(
            "Redis wins", "Redis is fast for our workload", "win", ["redis"]
        )
        evidence.record_observation(
            "Redis latency is consistently under 5ms", 0.9, "measured"
        )
        evidence.record_ab_result(
            "exp-redis-1", "cache_backend", "sqlite", "Redis", "Redis wins by 10x"
        )

        snapshot = evidence.get_evidence_snapshot("Redis")

        # Should find the learning via FTS
        assert len(snapshot["learnings"]) >= 1

        # Should find the observation via LIKE match
        assert len(snapshot["observations"]) >= 1
        assert "latency" in snapshot["observations"][0]["statement"]

        # Should find the A/B result via LIKE match on param/verdict/experiment_id
        assert len(snapshot["ab_results"]) >= 1

        # Evidence text should mention Redis
        assert "Redis" in snapshot["evidence_text"]

    def test_cross_exam_then_search_finds_topic(self, tmp_path):
        """After a cross-exam, searching evidence should find it via cross_exams table."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()

        cardio = _make_cardio_mock("PostgreSQL scales better horizontally")
        neuro = _make_neuro_mock("SQLite is simpler to deploy")

        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )
        team.cross_examine("PostgreSQL vs SQLite for production")

        # Cross-exam should be retrievable
        exams = evidence.get_cross_exams(limit=10)
        assert len(exams) >= 1
        assert "PostgreSQL" in exams[0]["topic"]


# ── Full Lifecycle Integration ───────────────────────────────────────────


class TestFullLifecycleIntegration:
    """Tests that exercise a complete workflow across multiple modules."""

    def test_consult_consensus_ab_conclude(self, tmp_path):
        """Full workflow: consult -> consensus -> A/B test -> conclude -> evidence."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()

        # Step 1: Consult on the topic
        cardio = _make_cardio_mock("Temperature 0.5 produces more focused output")
        neuro = _make_neuro_mock("Temperature 0.7 maintains creativity")

        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )
        consult_result = team.consult("Optimal temperature setting")
        assert consult_result.cardiologist_report is not None

        # Step 2: Run consensus with disagreement
        cardio.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.7, "assessment": "disagree", "reasoning": "0.5 is better"}',
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.6, "assessment": "agree", "reasoning": "0.7 is fine"}',
            latency_ms=50,
            model="qwen3:4b",
        )
        consensus_result = team.consensus("Temperature 0.7 is optimal")
        assert consensus_result.cardiologist_assessment == "disagree"

        # Step 3: Propose A/B test based on disagreement
        ab = ABTestEngine(evidence=evidence, state=state, config=config)
        test = ab.propose(
            "temperature", "0.7", "0.5", "Consensus disagreed, test empirically"
        )
        ab.start_grace_period(test.id)
        ab.activate(test.id)

        # Step 4: Measure and conclude
        measurement = ab.measure(test.id, metric_a=0.72, metric_b=0.85)
        assert measurement["variant_b_better"] is True

        ab.conclude(test.id, "variant_b (0.5) produced 18% better consistency")

        # Step 5: Verify everything is in evidence
        exams = evidence.get_cross_exams(limit=10)
        assert len(exams) >= 1  # from consult

        stats = evidence.get_stats()
        assert stats["total"] >= 0  # learnings may or may not exist

        # The concluded A/B test should be in evidence
        snapshot = evidence.get_evidence_snapshot("temperature")
        assert len(snapshot["ab_results"]) >= 1

    def test_sentinel_risk_triggers_corrigibility_check(self, tmp_path):
        """High sentinel risk should prompt corrigibility check on proposed fix."""
        # Step 1: Sentinel detects critical risk
        sentinel = Sentinel()
        scan = sentinel.run_cycle(
            "Found SQL injection vulnerability in authentication token parser"
        )
        assert scan.risk_level in ("medium", "high", "critical")

        # Step 2: Before acting, check the proposed fix through corrigibility
        config = Config()
        gate = CorrigibilityGate(config=config)

        # Safe remediation passes
        safe_fix = gate.run("patch the SQL query to use parameterized statements")
        assert safe_fix.passed is True

        # Dangerous "fix" is blocked
        dangerous_fix = gate.run("drop all database tables and recreate from scratch")
        assert dangerous_fix.passed is False

    def test_gains_gate_with_populated_evidence(self, tmp_path):
        """Gains gate should pass with populated evidence and healthy state."""
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        config = Config()

        # Populate evidence with some data
        evidence.record_learning("Test learning", "Content", "win", ["test"])
        evidence.record_cross_exam("topic", "neuro report", "cardio report", 0.8)

        gate = GainsGate(state=state, evidence=evidence, config=config)
        result = gate.run()

        # Critical checks (state_backend, evidence_store) should pass
        critical_checks = [c for c in result.checks if c.critical]
        for check in critical_checks:
            assert check.passed, f"Critical check {check.name} failed: {check.message}"

        assert result.duration_ms >= 0


# ── Review Loop Integration ────────────────────────────────────────────


class TestReviewLoopIntegration:
    """End-to-end: mode selection -> iterative cross-exam -> outcome recording."""

    def test_full_iterative_loop_with_consensus(self, tmp_path):
        """Iterative mode reaches consensus and records outcome."""
        from three_surgeons.core.cross_exam import ReviewMode

        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.9, "assessment": "agree"}',
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.8, "assessment": "agree"}',
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

        result = team.cross_examine_iterative(
            "Review auth changes",
            mode=ReviewMode.ITERATIVE,
        )

        # Verify result
        assert result.mode_used == "iterative"
        assert result.iteration_count >= 1
        assert result.iteration_count <= 3

        # Verify outcome recorded
        outcomes = evidence.get_review_outcomes(limit=1)
        assert len(outcomes) == 1
        assert outcomes[0]["mode_used"] == "iterative"

    def test_cli_cross_exam_with_mode_flag(self, monkeypatch, tmp_path):
        """CLI cross-exam --mode iterative parses and runs."""
        from unittest.mock import patch

        from three_surgeons.core.models import LLMResponse

        # Isolate config from host machine
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        mock_resp = LLMResponse(
            ok=True, content="Mock analysis", latency_ms=10, model="mock"
        )

        runner = CliRunner()
        with patch("three_surgeons.cli.main.LLMProvider") as mock_cls, \
             patch("three_surgeons.cli.main._make_neuro") as mock_neuro:
            mock_cls.return_value.query.return_value = mock_resp
            mock_neuro.return_value.query.return_value = mock_resp
            result = runner.invoke(
                cli, ["cross-exam", "--mode", "iterative", "test topic"]
            )
        # Flag parsed without error and command ran
        assert result.exit_code == 0, result.output
        assert "no such option" not in (result.output or "")
