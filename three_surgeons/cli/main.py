"""3-Surgeons CLI -- thin wrapper around core/.

Every command delegates to a core module. No business logic lives here.
Entry points: main() function and cli click group.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from three_surgeons.core.config import Config, SurgeonConfig
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.state import MemoryBackend


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
    click.echo("3-Surgeons Setup Wizard")
    click.echo("=" * 40)

    # Cardiologist config
    click.echo("\n--- Cardiologist (external model) ---")
    cardio_provider = click.prompt("Provider", default="openai")
    cardio_model = click.prompt("Model", default="gpt-4.1-mini")
    cardio_api_key_env = click.prompt("API key env var", default="OPENAI_API_KEY")

    # Neurologist config
    click.echo("\n--- Neurologist (local model) ---")
    neuro_provider = click.prompt("Provider", default="ollama")
    neuro_model = click.prompt("Model", default="qwen3:4b")
    neuro_endpoint = click.prompt("Endpoint", default="http://localhost:11434/v1")

    config_data = {
        "surgeons": {
            "cardiologist": {
                "provider": cardio_provider,
                "model": cardio_model,
                "api_key_env": cardio_api_key_env,
                "endpoint": "https://api.openai.com/v1",
                "role": "External perspective -- cross-examination, evidence",
            },
            "neurologist": {
                "provider": neuro_provider,
                "model": neuro_model,
                "endpoint": neuro_endpoint,
                "api_key_env": "",
                "role": "Local intelligence -- pattern recognition, corrigibility",
            },
        },
    }

    config_dir = Path.home() / ".3surgeons"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump(config_data, default_flow_style=False))

    click.echo(f"\nConfig written to {config_path}")
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
    state = MemoryBackend()
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
    state = MemoryBackend()
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
    state = MemoryBackend()
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
    state = MemoryBackend()
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
    state = MemoryBackend()
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
