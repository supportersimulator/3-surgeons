"""3-Surgeons CLI -- thin wrapper around core/.

Every command delegates to a core module. No business logic lives here.
Entry points: main() function and cli click group.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import yaml

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.state import create_backend_from_config


def _make_neuro(config: Config) -> LLMProvider:
    """Create neurologist LLMProvider with GPU lock for local providers."""
    if config.neurologist.provider in ("ollama", "mlx", "local", "vllm", "lmstudio"):
        from three_surgeons.core.priority_queue import make_gpu_locked_adapter

        lock_dir = Path(config.gpu_lock_path) if config.gpu_lock_path else None
        adapter = make_gpu_locked_adapter(config.neurologist, lock_dir=lock_dir)
        return LLMProvider(config.neurologist, query_adapter=adapter)
    return LLMProvider(config.neurologist)


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """3-Surgeons: Multi-model consensus system."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.discover()


# -- init -------------------------------------------------------------------


@cli.command()
@click.option("--detect", is_flag=True, help="Auto-detect local LLM backends")
def init(detect: bool) -> None:
    """Interactive setup wizard."""
    import shutil

    from three_surgeons.core.config import detect_local_backend

    click.echo("3-Surgeons Setup Wizard")
    click.echo("=" * 40)

    # Auto-detect local backends
    click.echo("\nScanning for local LLM backends...")
    backends = detect_local_backend()

    if backends:
        for b in backends:
            models_str = ", ".join(b["models"][:5]) if b["models"] else "no models listed"
            click.echo(f"  Detected: {b['provider']} on port {b['port']} ({models_str})")
    else:
        click.echo("  No local LLM backends detected.")

    # Build preset menu dynamically
    click.echo("\nChoose a preset:")
    click.echo("  1. Hybrid (Recommended) -- OpenAI + local LLM")
    click.echo("  2. API-Only -- OpenAI + DeepSeek (no local LLM)")
    click.echo("  3. Local-Only -- local LLM only ($0 cost)")
    click.echo("  4. Custom -- configure manually")
    preset = click.prompt("Selection", type=int, default=1)

    presets_dir = Path(__file__).parent.parent.parent / "config" / "presets"
    preset_map = {1: "hybrid.yaml", 2: "api-only.yaml", 3: "local-only.yaml"}

    config_dir = Path.home() / ".3surgeons"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    if preset in preset_map and (presets_dir / preset_map[preset]).exists():
        shutil.copy(presets_dir / preset_map[preset], config_path)

        # If a local backend was detected and preset uses local, patch the config
        if backends and preset in (1, 3):
            _patch_neurologist_from_detection(config_path, backends[0])

        click.echo(f"\nPreset '{preset_map[preset]}' written to {config_path}")
    else:
        # Manual config (custom wizard)
        # Pre-fill defaults from detected backend if available
        detected = backends[0] if backends else None
        default_neuro_provider = detected["provider"] if detected else "ollama"
        default_neuro_endpoint = detected["endpoint"] if detected else "http://localhost:11434/v1"
        default_neuro_model = detected["models"][0] if detected and detected["models"] else "qwen3:4b"

        click.echo("\n--- Cardiologist (external model) ---")
        cardio_provider = click.prompt("Provider", default="openai")
        cardio_model = click.prompt("Model", default="gpt-4.1-mini")
        cardio_endpoint = click.prompt("Endpoint", default="https://api.openai.com/v1")
        cardio_api_key_env = click.prompt("API key env var", default="OPENAI_API_KEY")

        click.echo(f"\n--- Neurologist (detected: {default_neuro_provider}) ---")
        neuro_provider = click.prompt("Provider", default=default_neuro_provider)
        neuro_model = click.prompt("Model", default=default_neuro_model)
        neuro_endpoint = click.prompt("Endpoint", default=default_neuro_endpoint)
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
    click.echo(
        "\nTip: If you're using a coding agent (Claude Code, Cursor, etc.), just ask it"
        "\n     to 'set up the surgery team' — it can detect your backends, help configure"
        "\n     API keys securely, and verify everything is connected."
    )


def _patch_neurologist_from_detection(config_path: Path, detected: dict) -> None:
    """Patch an existing config file to use the detected local backend."""
    raw = yaml.safe_load(config_path.read_text()) or {}
    surgeons = raw.get("surgeons", {})
    neuro = surgeons.get("neurologist", {})

    neuro["provider"] = detected["provider"]
    neuro["endpoint"] = detected["endpoint"]
    if detected["models"]:
        neuro["model"] = detected["models"][0]

    surgeons["neurologist"] = neuro
    raw["surgeons"] = surgeons
    config_path.write_text(yaml.dump(raw, default_flow_style=False))


# -- probe ------------------------------------------------------------------


@cli.command()
@click.pass_context
def probe(ctx: click.Context) -> None:
    """Health check all 3 surgeons with diagnostic details."""
    import httpx

    config: Config = ctx.obj["config"]
    click.echo("Probing surgeons...\n")

    all_ok = True
    for name, surgeon_cfg in [
        ("Cardiologist", config.cardiologist),
        ("Neurologist", config.neurologist),
    ]:
        # Step 1: Check if API key is needed and present
        is_local = surgeon_cfg.provider in ("ollama", "mlx", "local", "vllm", "lmstudio")
        if not is_local and not surgeon_cfg.get_api_key():
            env_var = surgeon_cfg.api_key_env or "(not configured)"
            click.echo(f"  {name}: FAIL -- API key missing. Set {env_var} env var.")
            all_ok = False
            continue

        # Step 2: Check endpoint reachability
        endpoint = surgeon_cfg.endpoint.rstrip("/")
        try:
            models_resp = httpx.get(f"{endpoint}/models", timeout=3.0)
            endpoint_ok = models_resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            click.echo(
                f"  {name}: FAIL -- endpoint unreachable ({endpoint}). "
                f"Is your {surgeon_cfg.provider} server running?"
            )
            all_ok = False
            continue
        except Exception as exc:
            click.echo(f"  {name}: FAIL -- endpoint error: {exc}")
            all_ok = False
            continue

        # Step 3: Check if the configured model exists
        model_found = True
        if endpoint_ok:
            try:
                data = models_resp.json()
                if isinstance(data, dict) and "data" in data:
                    available = [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
                    if available and surgeon_cfg.model not in available:
                        model_found = False
                        click.echo(
                            f"  {name}: WARN -- endpoint OK but model '{surgeon_cfg.model}' "
                            f"not found. Available: {', '.join(available[:5])}"
                        )
            except Exception:
                pass  # models listing is best-effort

        # Step 4: Test actual LLM call
        try:
            provider = LLMProvider(surgeon_cfg)
            resp = provider.ping(timeout_s=10.0)
            if resp.ok:
                status = "OK" if model_found else "OK (model responded but not in /models list)"
                click.echo(f"  {name}: {status} ({resp.latency_ms}ms)")
            else:
                click.echo(f"  {name}: FAIL -- endpoint reachable but query failed: {resp.content[:100]}")
                all_ok = False
        except Exception as exc:
            click.echo(f"  {name}: FAIL -- {exc}")
            all_ok = False

    click.echo(f"\nAtlas (Claude): always available (this session)")

    if not all_ok:
        click.echo("\nSome surgeons unreachable. Run '3s init' to reconfigure.")
        ctx.exit(1)
    else:
        click.echo("\nAll surgeons operational.")


# -- cross-exam -------------------------------------------------------------


@cli.command("cross-exam")
@click.argument("topic")
@click.option(
    "--mode",
    "review_mode",
    type=click.Choice(["single", "iterative", "continuous"], case_sensitive=False),
    default=None,
    help="Review loop depth: single (1 pass), iterative (up to 3), continuous (up to 5).",
)
@click.pass_context
def cross_exam(ctx: click.Context, topic: str, review_mode: Optional[str]) -> None:
    """Full cross-examination protocol."""
    from three_surgeons.core.cross_exam import ReviewMode, SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = _make_neuro(config)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    # Resolve mode: CLI flag > config default
    mode = ReviewMode.from_string(
        review_mode or config.review.depth
    )

    click.echo(f"Cross-examining ({mode.value} mode, max {mode.max_iterations} iterations): {topic}\n")
    result = team.cross_examine_iterative(topic, mode=mode)

    # Surface degradation warnings
    for warning in result.warnings:
        click.echo(f"  [WARNING] {warning}", err=True)
    if result.warnings:
        click.echo(f"  Proceeding with {result.surgeon_count}/2 external surgeons.\n", err=True)

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

    # Iteration summary
    if result.iteration_count > 1:
        click.echo(f"Iterations: {result.iteration_count}/{mode.max_iterations}")
    if result.escalation_needed:
        click.echo("[ESCALATION] Consensus not reached — human review needed.", err=True)
        if result.unresolved_summary:
            click.echo(f"  {result.unresolved_summary}", err=True)

    click.echo(f"Cost: ${result.total_cost:.4f} | Latency: {result.total_latency_ms:.0f}ms")


# -- mode -------------------------------------------------------------------


@cli.command("mode")
@click.argument("review_mode", required=False)
@click.option(
    "--duration",
    type=click.Choice(["session", "7d", "30d", "permanent"], case_sensitive=False),
    default="permanent",
    help="How long this mode setting lasts.",
)
@click.pass_context
def mode_cmd(ctx: click.Context, review_mode: Optional[str], duration: str) -> None:
    """Show or set the default review depth mode.

    Without arguments: shows current mode.
    With a mode argument: sets the default mode.
    """
    config: Config = ctx.obj["config"]

    if review_mode is None:
        # Show current mode
        click.echo(f"Current review depth: {config.review.depth}")
        click.echo(f"Auto-depth: {config.review.auto_depth}")
        return

    from three_surgeons.core.cross_exam import ReviewMode

    mode = ReviewMode.from_string(review_mode)
    click.echo(f"Review depth set to: {mode.value} (duration: {duration})")
    click.echo(f"  Max iterations per review: {mode.max_iterations}")

    if duration == "permanent":
        # Persist to ~/.3surgeons/config.yaml
        config_path = Path.home() / ".3surgeons" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        raw = {}
        if config_path.is_file():
            raw = yaml.safe_load(config_path.read_text()) or {}
        raw.setdefault("review", {})["depth"] = mode.value
        config_path.write_text(yaml.dump(raw, default_flow_style=False))
        click.echo(f"  Saved to {config_path}. Use '3s mode single' to revert.")
    else:
        click.echo(f"  Duration '{duration}' is session-display only (not persisted to config).")


# -- review-weights ---------------------------------------------------------


@cli.group("review-weights", invoke_without_command=True)
@click.pass_context
def review_weights(ctx: click.Context) -> None:
    """Manage adaptive review depth weights."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(weights_show)


@review_weights.command("show")
@click.pass_context
def weights_show(ctx: click.Context) -> None:
    """Show current learned mode weights."""
    config: Config = ctx.obj["config"]
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    weights = evidence.get_mode_weights()
    if not weights:
        click.echo("No review outcomes recorded yet. Weights will build over time.")
        return
    click.echo("Learned review depth weights:")
    for mode_name, weight in sorted(weights.items()):
        click.echo(f"  {mode_name}: {weight:.3f}")


@review_weights.command("export")
@click.option("--output", "-o", default="-", help="Output file (default: stdout)")
@click.pass_context
def weights_export(ctx: click.Context, output: str) -> None:
    """Export review outcomes for cross-machine sharing."""
    import json

    config: Config = ctx.obj["config"]
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    data = evidence.export_review_outcomes()
    json_str = json.dumps(data, indent=2)
    if output == "-":
        click.echo(json_str)
    else:
        Path(output).write_text(json_str)
        click.echo(f"Exported {len(data)} outcomes to {output}")


@review_weights.command("import")
@click.argument("input_file", type=click.Path(exists=True))
@click.pass_context
def weights_import(ctx: click.Context, input_file: str) -> None:
    """Import review outcomes from another machine."""
    import json

    config: Config = ctx.obj["config"]
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    data = json.loads(Path(input_file).read_text())
    count = evidence.import_review_outcomes(data)
    click.echo(f"Imported {count} review outcomes.")


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
    neuro = _make_neuro(config)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    click.echo(f"Consulting on: {topic}\n")
    result = team.consult(topic)

    # Surface degradation warnings
    for warning in result.warnings:
        click.echo(f"  [WARNING] {warning}", err=True)

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
    neuro = _make_neuro(config)
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
    neuro = _make_neuro(config)
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
    neuro = _make_neuro(config)
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
    neuro = _make_neuro(config)
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
    neuro = _make_neuro(config)
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
    neuro = _make_neuro(config)
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


# -- docs-init ---------------------------------------------------------------


@cli.command("docs-init")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--scan", is_flag=True, help="Auto-detect projects in repo")
@click.option("--no-gitignore", is_flag=True, help="Skip .gitignore update")
def docs_init(path: str, scan: bool, no_gitignore: bool) -> None:
    """Set up 4-folder document system (inbox/vision/reflect/dao)."""
    from three_surgeons.core.doc_organizer import init_docs, scan_repo

    target = Path(path).resolve()

    if scan:
        click.echo(f"Scanning {target} for project structure...\n")
        scan_result = scan_repo(target)

        if scan_result.is_superrepo:
            click.echo("Detected: superrepo with submodules\n")

        if scan_result.projects:
            click.echo("Detected projects:\n")
            for p in scan_result.projects:
                marker = "*" if p.recommended else " "
                click.echo(f"  [{marker}] {p.name}/ -- {p.reason}"
                           f" (score={p.score})")
            click.echo()

            recommended = [p for p in scan_result.projects if p.recommended]
            if recommended:
                click.echo(f"Recommendation: Create 4-folder system in repo root + "
                           f"{len(recommended)} project(s):")
                for p in recommended:
                    click.echo(f"  - {p.name}/")
                click.echo()

            if not click.confirm("Set up 4 folders in repo root?", default=True):
                click.echo("Aborted.")
                return

            result = init_docs(target, update_gitignore=not no_gitignore)
            _print_init_result(result, "repo root")

            for p in recommended:
                if click.confirm(f"Set up 4 folders in {p.name}/?", default=True):
                    r = init_docs(p.path, update_gitignore=not no_gitignore)
                    _print_init_result(r, p.name)
        else:
            click.echo("No distinct sub-projects detected. Setting up in repo root.\n")
            result = init_docs(target, update_gitignore=not no_gitignore)
            _print_init_result(result, "repo root")
    else:
        result = init_docs(target, update_gitignore=not no_gitignore)
        _print_init_result(result, str(target.name))

    click.echo("\nDone. Documents don't move between folders -- each generates independently.")
    click.echo("Run '3s docs-init --scan' to detect sub-projects in monorepos.")


def _print_init_result(result, label: str) -> None:
    """Print the result of a docs-init operation."""
    if result.folders_created:
        click.echo(f"  [{label}] Created: {', '.join(result.folders_created)}")
    if result.already_existed:
        click.echo(f"  [{label}] Already existed: {', '.join(result.already_existed)}")
    if result.gitignore_updated:
        click.echo(f"  [{label}] Updated .gitignore")


# -- docs-scan ---------------------------------------------------------------


@cli.command("docs-scan")
@click.argument("path", default=".", type=click.Path(exists=True))
def docs_scan(path: str) -> None:
    """Scan repo for projects that deserve their own 4 folders."""
    from three_surgeons.core.doc_organizer import scan_repo

    target = Path(path).resolve()
    click.echo(f"Scanning {target}...\n")
    scan_result = scan_repo(target)

    if scan_result.is_superrepo:
        click.echo("Type: superrepo (has .gitmodules)\n")

    if not scan_result.projects:
        click.echo("No distinct sub-projects detected.")
        click.echo("This looks like a single project -- run '3s docs-init' to set up folders.")
        return

    click.echo("Detected projects:\n")
    for p in scan_result.projects:
        marker = "recommend" if p.recommended else "skip"
        sub = " (submodule)" if p.is_submodule else ""
        click.echo(f"  {p.name}/{sub}")
        click.echo(f"    {p.reason} | score={p.score} | {marker}")
        click.echo()

    recommended = [p for p in scan_result.projects if p.recommended]
    skipped = [p for p in scan_result.projects if not p.recommended]
    click.echo(f"Recommend 4 folders: repo root + {len(recommended)} project(s)")
    if skipped:
        click.echo(f"Skip {len(skipped)}: {', '.join(p.name for p in skipped)} "
                    f"(shared/utility, fewer independence signals)")
    click.echo(f"\nRun '3s docs-init --scan' to set up all recommended projects.")


# -- serve ------------------------------------------------------------------


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address")
@click.option("--port", default=3456, type=int, help="Port (default: 3456)")
def serve(host: str, port: int) -> None:
    """Start the 3-Surgeons HTTP server (Layer 2)."""
    import sys

    _mod = sys.modules[__name__]

    # Use module-level attributes if set (allows test patching),
    # otherwise do lazy imports.
    if not hasattr(_mod, "uvicorn") or not hasattr(_mod, "create_app"):
        try:
            import uvicorn as _uvicorn

            from three_surgeons.http.server import create_app as _create_app

            _mod.uvicorn = _uvicorn
            _mod.create_app = _create_app
        except ImportError:
            click.echo(
                "Error: HTTP dependencies not installed. "
                "Run: pip install 'three-surgeons[http]'"
            )
            raise SystemExit(1)

    click.echo(f"3-Surgeons server starting on {host}:{port}")
    app = _mod.create_app()
    _mod.uvicorn.run(app, host=host, port=port)


# -- main entry point -------------------------------------------------------


def main() -> None:
    """Entry point for the 3s console script."""
    cli()


if __name__ == "__main__":
    main()
