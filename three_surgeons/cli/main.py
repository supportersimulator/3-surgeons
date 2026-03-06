"""3-Surgeons CLI -- thin wrapper around core/.

Every command delegates to a core module. No business logic lives here.
Entry points: main() function and cli click group.
"""
from __future__ import annotations

from pathlib import Path

import click
import yaml

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.state import create_backend_from_config


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """3-Surgeons: Multi-model consensus system."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.discover()


# -- init -------------------------------------------------------------------


@cli.command()
def init() -> None:
    """Interactive setup wizard."""
    import shutil

    click.echo("3-Surgeons Setup Wizard")
    click.echo("=" * 40)

    # Preset selection
    click.echo("\nChoose a preset:")
    click.echo("  1. Hybrid (Recommended) -- OpenAI + local Ollama")
    click.echo("  2. API-Only -- OpenAI + DeepSeek (no local LLM)")
    click.echo("  3. Local-Only -- Ollama only ($0 cost)")
    click.echo("  4. Custom -- configure manually")
    preset = click.prompt("Selection", type=int, default=1)

    presets_dir = Path(__file__).parent.parent.parent / "config" / "presets"
    preset_map = {1: "hybrid.yaml", 2: "api-only.yaml", 3: "local-only.yaml"}

    config_dir = Path.home() / ".3surgeons"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    if preset in preset_map and (presets_dir / preset_map[preset]).exists():
        shutil.copy(presets_dir / preset_map[preset], config_path)
        click.echo(f"\nPreset '{preset_map[preset]}' written to {config_path}")
    else:
        # Manual config (custom wizard)
        click.echo("\n--- Cardiologist (external model) ---")
        cardio_provider = click.prompt("Provider", default="openai")
        cardio_model = click.prompt("Model", default="gpt-4.1-mini")
        cardio_endpoint = click.prompt("Endpoint", default="https://api.openai.com/v1")
        cardio_api_key_env = click.prompt("API key env var", default="OPENAI_API_KEY")

        click.echo("\n--- Neurologist ---")
        neuro_provider = click.prompt("Provider", default="ollama")
        neuro_model = click.prompt("Model", default="qwen3:4b")
        neuro_endpoint = click.prompt("Endpoint", default="http://localhost:11434/v1")
        neuro_api_key_env = click.prompt("API key env var (blank if local)", default="")

        config_data = {
            "surgeons": {
                "cardiologist": {
                    "provider": cardio_provider,
                    "model": cardio_model,
                    "endpoint": cardio_endpoint,
                    "api_key_env": cardio_api_key_env,
                    "role": "External perspective -- cross-examination, evidence",
                },
                "neurologist": {
                    "provider": neuro_provider,
                    "model": neuro_model,
                    "endpoint": neuro_endpoint,
                    "api_key_env": neuro_api_key_env,
                    "role": "Local intelligence -- pattern recognition, corrigibility",
                },
            },
            "state": {"backend": "sqlite", "sqlite_path": "~/.3surgeons/state.db"},
            "budgets": {"daily_external_usd": 5.0},
            "evidence": {"db_path": "~/.3surgeons/evidence.db"},
        }
        config_path.write_text(yaml.dump(config_data, default_flow_style=False))
        click.echo(f"\nConfig written to {config_path}")

    click.echo("\nSecurity reminder: NEVER commit API keys. Use environment variables.")
    click.echo("Run '3s probe' to verify connectivity.")


# -- probe ------------------------------------------------------------------


@cli.command()
@click.pass_context
def probe(ctx: click.Context) -> None:
    """Health check all 3 surgeons."""
    config: Config = ctx.obj["config"]
    click.echo("Probing surgeons...\n")

    all_ok = True
    for name, surgeon_cfg in [
        ("Cardiologist", config.cardiologist),
        ("Neurologist", config.neurologist),
    ]:
        try:
            provider = LLMProvider(surgeon_cfg)
            resp = provider.ping(timeout_s=5.0)
            if resp.ok:
                click.echo(f"  {name}: OK ({resp.latency_ms}ms)")
            else:
                click.echo(f"  {name}: FAIL -- {resp.content[:80]}")
                all_ok = False
        except Exception as exc:
            click.echo(f"  {name}: UNREACHABLE -- {exc}")
            all_ok = False

    click.echo(f"\nAtlas (Claude): always available (this session)")

    if not all_ok:
        click.echo("\nSome surgeons unreachable. Check config with '3s init'.")
        ctx.exit(1)
    else:
        click.echo("\nAll surgeons operational.")


# -- cross-exam -------------------------------------------------------------


@cli.command("cross-exam")
@click.argument("topic")
@click.pass_context
def cross_exam(ctx: click.Context, topic: str) -> None:
    """Full cross-examination protocol."""
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = LLMProvider(config.neurologist)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    click.echo(f"Cross-examining: {topic}\n")
    result = team.cross_examine(topic)

    if result.cardiologist_report:
        click.echo("--- Cardiologist ---")
        click.echo(result.cardiologist_report)
        click.echo()
    if result.neurologist_report:
        click.echo("--- Neurologist ---")
        click.echo(result.neurologist_report)
        click.echo()
    if result.cardiologist_exploration or result.neurologist_exploration:
        click.echo("=== Open Exploration (unknown unknowns) ===")
        if result.cardiologist_exploration:
            click.echo("--- Cardiologist Exploration ---")
            click.echo(result.cardiologist_exploration)
            click.echo()
        if result.neurologist_exploration:
            click.echo("--- Neurologist Exploration ---")
            click.echo(result.neurologist_exploration)
            click.echo()
    if result.synthesis:
        click.echo("--- Synthesis ---")
        click.echo(result.synthesis)
        click.echo()

    click.echo(f"Cost: ${result.total_cost:.4f} | Latency: {result.total_latency_ms:.0f}ms")


# -- consult ----------------------------------------------------------------


@cli.command()
@click.argument("topic")
@click.pass_context
def consult(ctx: click.Context, topic: str) -> None:
    """Quick consult with both surgeons."""
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = LLMProvider(config.neurologist)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    click.echo(f"Consulting on: {topic}\n")
    result = team.consult(topic)

    if result.cardiologist_report:
        click.echo("--- Cardiologist ---")
        click.echo(result.cardiologist_report)
        click.echo()
    if result.neurologist_report:
        click.echo("--- Neurologist ---")
        click.echo(result.neurologist_report)
        click.echo()

    click.echo(f"Cost: ${result.total_cost:.4f} | Latency: {result.total_latency_ms:.0f}ms")


# -- consensus --------------------------------------------------------------


@cli.command()
@click.argument("claim")
@click.pass_context
def consensus(ctx: click.Context, claim: str) -> None:
    """Confidence-weighted consensus on a claim."""
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = LLMProvider(config.neurologist)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    click.echo(f"Consensus on: {claim}\n")
    result = team.consensus(claim)

    click.echo(f"  Cardiologist: {result.cardiologist_assessment} "
               f"(confidence={result.cardiologist_confidence:.2f})")
    click.echo(f"  Neurologist:  {result.neurologist_assessment} "
               f"(confidence={result.neurologist_confidence:.2f})")
    click.echo(f"  Weighted score: {result.weighted_score:+.2f}")
    click.echo(f"  Total cost: ${result.total_cost:.4f}")


# -- sentinel ---------------------------------------------------------------


@cli.command("sentinel")
@click.argument("content")
@click.pass_context
def sentinel_run(ctx: click.Context, content: str) -> None:
    """Run complexity vector sentinel."""
    from three_surgeons.core.sentinel import Sentinel

    sentinel = Sentinel()
    result = sentinel.run_cycle(content)

    click.echo(f"Sentinel scan: {result.vectors_checked} vectors checked")
    click.echo(f"Triggered: {result.vectors_triggered} | Risk: {result.risk_level} "
               f"| Score: {result.overall_score:.2f}")

    if result.triggered_vectors:
        click.echo("\nTriggered vectors:")
        for tv in result.triggered_vectors:
            click.echo(f"  [{tv['id']}] {tv['name']} -- {tv['hits']} hits "
                       f"(risk={tv['risk_score']:.1f})")

    if result.recommendations:
        click.echo("\nRecommendations:")
        for rec in result.recommendations:
            click.echo(f"  - {rec}")


# -- gains-gate -------------------------------------------------------------


@cli.command("gains-gate")
@click.pass_context
def gains_gate(ctx: click.Context) -> None:
    """Run gains gate verification."""
    from three_surgeons.core.gates import GainsGate

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    gate = GainsGate(state=state, evidence=evidence, config=config)

    click.echo("Running gains gate...\n")
    result = gate.run()

    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        crit = " [critical]" if check.critical else ""
        click.echo(f"  [{status}]{crit} {check.name}: {check.message}")

    click.echo(f"\n{result.summary} ({result.duration_ms:.0f}ms)")

    if not result.passed:
        ctx.exit(1)


# -- neurologist-pulse -------------------------------------------------------


@cli.command("neurologist-pulse")
@click.pass_context
def neurologist_pulse_cmd(ctx: click.Context) -> None:
    """System health pulse check via neurologist."""
    from three_surgeons.core.neurologist import neurologist_pulse

    config: Config = ctx.obj["config"]
    neuro = LLMProvider(config.neurologist)
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))

    click.echo("Running neurologist pulse...\n")
    result = neurologist_pulse(
        neuro, state_backend=state, evidence_store=evidence,
        gpu_lock_path=config.gpu_lock_path,
    )

    for name, check in result.checks.items():
        status = "OK" if check.ok else "FAIL"
        latency = f" ({check.latency_ms:.0f}ms)" if check.latency_ms > 0 else ""
        click.echo(f"  [{status}] {name}: {check.detail}{latency}")

    click.echo(f"\n{result.summary}")
    if not result.healthy:
        ctx.exit(1)


# -- neurologist-challenge ---------------------------------------------------


@cli.command("neurologist-challenge")
@click.argument("topic")
@click.pass_context
def neurologist_challenge_cmd(ctx: click.Context, topic: str) -> None:
    """Corrigibility skeptic challenge on a topic."""
    from three_surgeons.core.neurologist import neurologist_challenge

    config: Config = ctx.obj["config"]
    neuro = LLMProvider(config.neurologist)
    evidence = EvidenceStore(str(config.evidence.resolved_path))

    click.echo(f"Challenging: {topic}\n")
    result = neurologist_challenge(topic, neuro, evidence_store=evidence)

    if result.challenges:
        for c in result.challenges:
            icon = {"critical": "!!", "worth_testing": "?", "informational": "i"}.get(c.severity, "?")
            click.echo(f"  [{icon}] {c.claim}")
            click.echo(f"      Challenge: {c.challenge}")
            if c.suggested_test:
                click.echo(f"      Test: {c.suggested_test}")
            click.echo()
    else:
        click.echo("  No challenges found.")


# -- introspect --------------------------------------------------------------


@cli.command("introspect")
@click.pass_context
def introspect_cmd(ctx: click.Context) -> None:
    """Ask each surgeon to self-report capabilities."""
    from three_surgeons.core.neurologist import introspect

    config: Config = ctx.obj["config"]
    providers = {}
    for name, cfg in [("cardiologist", config.cardiologist), ("neurologist", config.neurologist)]:
        try:
            providers[name] = LLMProvider(cfg)
        except Exception:
            pass

    click.echo("Introspecting surgeons...\n")
    results = introspect(providers)

    for name, result in results.items():
        status = "OK" if result.ok else "FAIL"
        click.echo(f"  {name} ({result.model}): [{status}]")
        if result.capabilities:
            click.echo(f"    {result.capabilities[:200]}")
        click.echo()


# -- ask-local ---------------------------------------------------------------


@cli.command("ask-local")
@click.argument("prompt")
@click.pass_context
def ask_local_cmd(ctx: click.Context, prompt: str) -> None:
    """Direct query to the neurologist (local model)."""
    from three_surgeons.core.direct import ask_local

    config: Config = ctx.obj["config"]
    neuro = LLMProvider(config.neurologist)
    resp = ask_local(prompt, neuro)

    if resp.ok:
        click.echo(resp.content)
    else:
        click.echo(f"Error: {resp.content}", err=True)
        ctx.exit(1)


# -- ask-remote --------------------------------------------------------------


@cli.command("ask-remote")
@click.argument("prompt")
@click.pass_context
def ask_remote_cmd(ctx: click.Context, prompt: str) -> None:
    """Direct query to the cardiologist (remote model)."""
    from three_surgeons.core.direct import ask_remote

    config: Config = ctx.obj["config"]
    cardio = LLMProvider(config.cardiologist)
    resp = ask_remote(prompt, cardio)

    if resp.ok:
        click.echo(resp.content)
        click.echo(f"\nCost: ${resp.cost_usd:.4f}")
    else:
        click.echo(f"Error: {resp.content}", err=True)
        ctx.exit(1)


# -- cardio-review -----------------------------------------------------------


@cli.command("cardio-review")
@click.argument("topic")
@click.option("--git-context", default=None, help="Recent git changes context")
@click.pass_context
def cardio_review_cmd(ctx: click.Context, topic: str, git_context: str) -> None:
    """Cardiologist cross-examination review."""
    from three_surgeons.core.cardio import cardio_review
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = LLMProvider(config.neurologist)
    team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state)

    click.echo(f"Cardio review: {topic}\n")
    result = cardio_review(topic, team, evidence_store=evidence, git_context=git_context)

    click.echo("--- Cardiologist ---")
    click.echo(result.cardiologist_findings)
    click.echo("\n--- Neurologist ---")
    click.echo(result.neurologist_blind_spots)
    click.echo("\n--- Synthesis ---")
    click.echo(result.synthesis)

    if result.dissent:
        click.echo(f"\nDissent: {result.dissent}")
    if result.recommendations:
        click.echo("\nRecommendations:")
        for r in result.recommendations:
            click.echo(f"  - {r}")


# -- ab-validate -------------------------------------------------------------


@cli.command("ab-validate")
@click.argument("description")
@click.pass_context
def ab_validate_cmd(ctx: click.Context, description: str) -> None:
    """Quick 3-surgeon fix validation."""
    from three_surgeons.core.cardio import ab_validate
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = LLMProvider(config.neurologist)
    team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state)

    click.echo(f"Validating: {description}\n")
    result = ab_validate(description, team)

    click.echo(f"  Verdict: {result.verdict}")
    click.echo(f"  Reasoning: {result.reasoning}")
    if result.surgeon_votes:
        click.echo("  Votes:")
        for name, vote in result.surgeon_votes.items():
            click.echo(f"    {name}: {vote}")


# -- research ----------------------------------------------------------------


@cli.command("research")
@click.argument("topic")
@click.pass_context
def research_cmd(ctx: click.Context, topic: str) -> None:
    """Self-directed research on a topic."""
    from three_surgeons.core.research import research

    config: Config = ctx.obj["config"]
    cardio = LLMProvider(config.cardiologist)

    click.echo(f"Researching: {topic}\n")
    result = research(topic, cardio)

    if result.findings:
        click.echo("Findings:")
        for f in result.findings:
            click.echo(f"  - {f}")
    if result.sources:
        click.echo(f"\nSources: {', '.join(result.sources)}")
    click.echo(f"\nCost: ${result.cost_usd:.4f}")


# -- ab-propose -------------------------------------------------------------


@cli.command("ab-propose")
@click.argument("param")
@click.argument("variant_a")
@click.argument("variant_b")
@click.argument("hypothesis")
@click.pass_context
def ab_propose(
    ctx: click.Context,
    param: str,
    variant_a: str,
    variant_b: str,
    hypothesis: str,
) -> None:
    """Propose an A/B test."""
    from three_surgeons.core.ab_testing import ABTestEngine

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    engine = ABTestEngine(evidence=evidence, state=state, config=config)

    try:
        test = engine.propose(
            param=param,
            variant_a=variant_a,
            variant_b=variant_b,
            hypothesis=hypothesis,
        )
        click.echo(f"A/B test proposed: {test.id}")
        click.echo(f"  Param: {test.param}")
        click.echo(f"  A: {test.variant_a} vs B: {test.variant_b}")
        click.echo(f"  Hypothesis: {test.hypothesis}")
        click.echo(f"  Status: {test.status.value}")
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        ctx.exit(1)


# -- main entry point -------------------------------------------------------


def main() -> None:
    """Entry point for the 3s console script."""
    cli()
