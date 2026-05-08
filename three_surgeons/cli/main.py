"""3-Surgeons CLI -- thin wrapper around core/.

Every command delegates to a core module. No business logic lives here.
Entry points: main() function and cli click group.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import json

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


def _detect_ides() -> list[str]:
    """Auto-detect installed IDEs by checking marker directories."""
    import os
    markers = {
        "Claude Code": "~/.claude",
        "Cursor": "~/.cursor",
        "VS Code": "~/.config/Code",
        "VS Code (macOS)": "~/Library/Application Support/Code",
        "Windsurf": "~/.windsurf",
        "Zed": "~/.config/zed",
        "OpenCode": "~/.config/opencode",
    }
    detected = []
    for ide, path in markers.items():
        if os.path.isdir(os.path.expanduser(path)):
            detected.append(ide)
    return detected


@click.group()
@click.option(
    "--cardio-provider",
    "cardio_provider",
    type=click.Choice(["openai", "deepseek", "anthropic"], case_sensitive=False),
    default=None,
    help=(
        "Override the Cardiologist provider for this invocation. "
        "openai (default) keeps gpt-4.1-mini; deepseek routes to "
        "https://api.deepseek.com/v1 with deepseek-chat; anthropic routes "
        "to https://api.anthropic.com/v1 with claude-haiku-4-5-20251001 "
        "(restores 3-surgeon model diversity when both OpenAI billing is "
        "down and neuro is pinned to DeepSeek). Reads Context_DNA_Deepseek "
        "(or DEEPSEEK_API_KEY) / Context_DNA_Anthropic (or ANTHROPIC_API_KEY)."
    ),
)
@click.option(
    "--neuro-provider",
    "neuro_provider",
    type=click.Choice(["ollama", "mlx", "deepseek"], case_sensitive=False),
    default=None,
    help=(
        "Override the Neurologist provider for this invocation. "
        "ollama (default) keeps qwen3:4b on localhost:11434; mlx targets "
        "localhost:5044; deepseek routes to https://api.deepseek.com/v1 "
        "with deepseek-chat. Env var CONTEXT_DNA_NEURO_PROVIDER does the "
        "same fleet-wide. Per CLAUDE.md 2026-04-26 cutover directive."
    ),
)
@click.pass_context
def cli(
    ctx: click.Context,
    cardio_provider: Optional[str],
    neuro_provider: Optional[str],
) -> None:
    """3-Surgeons: Multi-model consensus system."""
    ctx.ensure_object(dict)
    config = Config.discover()
    if cardio_provider:
        try:
            # require_key=False so --help, probe, and setup-check still run
            # without a key present; commands that actually call the model
            # will surface the missing key via the normal error path.
            config.apply_cardiologist_provider(cardio_provider, require_key=False)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        ctx.obj["cardio_provider_override"] = cardio_provider.lower()
    if neuro_provider:
        try:
            config.apply_neurologist_provider(neuro_provider, require_key=False)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        ctx.obj["neuro_provider_override"] = neuro_provider.lower()
    ctx.obj["config"] = config


# -- init -------------------------------------------------------------------


@cli.command()
@click.option("--detect", is_flag=True, help="Auto-detect local LLM backends")
def init(detect: bool) -> None:
    """Interactive setup wizard."""
    import shutil
    import sys

    from three_surgeons.core.config import detect_local_backend

    click.echo("3-Surgeons Setup Wizard")
    click.echo("=" * 40)

    # Python version check — MCP server requires 3.10+
    py_version = sys.version_info
    click.echo(f"\nPython: {py_version.major}.{py_version.minor}.{py_version.micro}")
    if py_version < (3, 10):
        click.echo(
            "\n  WARNING: Python 3.10+ is required for the MCP server (IDE tools).\n"
            f"  You have Python {py_version.major}.{py_version.minor}.\n"
        )
        click.echo("  Install a newer Python:")
        click.echo("    macOS:   brew install python@3.12")
        click.echo("    pyenv:   pyenv install 3.12 && pyenv global 3.12")
        click.echo("    Ubuntu:  sudo apt install python3.12 python3.12-venv")
        click.echo("    Windows: winget install Python.Python.3.12")
        click.echo(
            "\n  After installing, recreate the venv:"
            "\n    python3.12 -m venv .venv && .venv/bin/pip install -e '.[mcp]'"
        )
        if not click.confirm("\n  Continue setup anyway? (skills work without MCP)", default=True):
            raise SystemExit(1)

    # Auto-detect local backends
    click.echo("\nScanning for local LLM backends...")
    backends = detect_local_backend()

    if backends:
        for b in backends:
            models_str = ", ".join(b["models"][:5]) if b["models"] else "no models listed"
            click.echo(f"  Detected: {b['provider']} on port {b['port']} ({models_str})")
    else:
        click.echo("  No local LLM backends detected.")

    # Build preset menu dynamically based on what was detected
    click.echo("\nChoose a preset:")
    if backends:
        detected_name = backends[0]["provider"].upper()
        click.echo(f"  1. Hybrid (Recommended) -- OpenAI + {detected_name} (detected)")
        if any(b["provider"] == "mlx" for b in backends):
            click.echo("     ^ Uses your mlx_lm.server on port 5044")
        elif any(b["provider"] == "ollama" for b in backends):
            click.echo("     ^ Uses your Ollama server on port 11434")
    else:
        click.echo("  1. Hybrid -- OpenAI + local LLM (no local backend detected)")
        click.echo("     Supported: mlx_lm.server | Ollama | LM Studio | vLLM")
    click.echo("  2. API-Only -- OpenAI + DeepSeek (no local LLM needed)")
    click.echo("     Requires: Context_DNA_OPENAI + Context_DNA_Deepseek env vars")
    click.echo("  3. Local-Only -- local LLM only ($0 cost, needs local server)")
    click.echo("  4. Custom -- configure manually")

    # Suggest best default based on detection
    if backends:
        default_preset = 1
    else:
        click.echo("\n  No local LLM detected. Preset 2 (API-Only) may be easiest to start.")
        default_preset = 2

    preset = click.prompt("Selection", type=int, default=default_preset)

    presets_dir = Path(__file__).parent.parent.parent / "config" / "presets"
    # Use MLX-specific preset if MLX was detected
    hybrid_preset = "hybrid.yaml"
    if backends and any(b["provider"] == "mlx" for b in backends):
        hybrid_preset = "mlx-hybrid.yaml"
    preset_map = {1: hybrid_preset, 2: "api-only.yaml", 3: "local-only.yaml"}

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
        cardio_api_key_env = click.prompt("API key env var", default="Context_DNA_OPENAI")

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

    # IDE auto-detection
    detected = _detect_ides()
    if detected:
        click.echo(f"\nDetected IDEs: {', '.join(detected)}")
    else:
        click.echo("\nNo supported IDEs detected")

    click.echo("\nSecurity reminder: NEVER commit API keys. Use environment variables.")
    click.echo("Run '3s probe' to verify all surgeons are connected.")
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


def _bootstrap_api_key_from_keychain(env_var: str) -> bool:
    """Populate ``os.environ[env_var]`` from macOS keychain if missing.

    Returns True when the key is present in the environment after the call
    (either was already set or was successfully fetched). False when no
    keychain item exists or the platform is not macOS.

    Tries the requested env-var name first, then falls back to
    ``DEEPSEEK_API_KEY`` so deepseek probes succeed when the user only
    stores the canonical name. Silent on failure — keychain is a
    best-effort convenience, callers still validate via ``get_api_key()``.
    """
    import os
    import shutil
    import subprocess

    if not env_var:
        return False
    if os.environ.get(env_var):
        return True
    if shutil.which("security") is None:
        return False
    candidates = [env_var]
    if env_var != "DEEPSEEK_API_KEY":
        candidates.append("DEEPSEEK_API_KEY")
    for name in candidates:
        try:
            value = subprocess.run(
                ["security", "find-generic-password", "-s", name, "-w"],
                capture_output=True, text=True, timeout=3.0,
            ).stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            continue
        if value and len(value) >= 6:
            os.environ[env_var] = value
            return True
    return False


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def probe(ctx: click.Context, dry_run: bool) -> None:
    """Health check all 3 surgeons with diagnostic details."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("probe", {})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    import socket
    from urllib.parse import urlparse

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
            # Try to self-bootstrap from macOS keychain before failing.
            _bootstrap_api_key_from_keychain(surgeon_cfg.api_key_env)
        if not is_local and not surgeon_cfg.get_api_key():
            env_var = surgeon_cfg.api_key_env or "(not configured)"
            click.echo(f"  {name}: FAIL -- API key missing. Set {env_var} env var.")
            all_ok = False
            continue

        # Step 2: Check endpoint reachability.
        # Local LLM servers (mlx, ollama) sometimes block the HTTP loop while
        # loading or generating, which makes /v1/models hang. Use a TCP probe
        # to distinguish "process not listening" from "listening but slow",
        # and treat slow listings as a soft warning rather than fatal.
        endpoint = surgeon_cfg.endpoint.rstrip("/")
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        tcp_ok = False
        try:
            with socket.create_connection((host, port), timeout=2.0):
                tcp_ok = True
        except OSError:
            tcp_ok = False
        if not tcp_ok:
            click.echo(
                f"  {name}: FAIL -- endpoint unreachable ({endpoint}). "
                f"Is your {surgeon_cfg.provider} server running?"
            )
            all_ok = False
            continue

        endpoint_ok = False
        models_resp = None
        listing_slow = False
        try:
            models_resp = httpx.get(f"{endpoint}/models", timeout=5.0)
            endpoint_ok = models_resp.status_code == 200
        except httpx.TimeoutException:
            # TCP listener is up but /models is slow — common on local MLX
            # while a model is loading. Skip the listing and proceed to ping.
            listing_slow = True
        except Exception as exc:
            click.echo(f"  {name}: FAIL -- endpoint error: {exc}")
            all_ok = False
            continue

        # Step 3: Check if the configured model exists
        model_found = True
        if endpoint_ok and models_resp is not None:
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

        # Step 4: Test actual LLM call. Local models can be slow on first
        # token (cold load); give them more headroom than remote APIs.
        # Wire in fallback providers from config so a stalled local server
        # falls through to its remote backup instead of failing the probe —
        # matches the behaviour of every other call site (consult, cross-
        # examine, gates) which use the fallbacks list automatically.
        # When a fallback is available we shorten the primary timeout so a
        # hung local server flips to the fallback within ~10s instead of
        # blocking the probe for the full minute.
        fallbacks = surgeon_cfg.get_fallback_configs() or None
        if is_local and fallbacks:
            ping_timeout = 12.0
        elif is_local:
            ping_timeout = 60.0
        else:
            ping_timeout = 15.0
        if fallbacks:
            for fb in fallbacks:
                if fb.api_key_env:
                    _bootstrap_api_key_from_keychain(fb.api_key_env)
        try:
            provider = LLMProvider(surgeon_cfg, fallbacks=fallbacks)
            resp = provider.ping(timeout_s=ping_timeout)
            if resp.ok:
                if resp.model and resp.model != surgeon_cfg.model:
                    status = f"OK via fallback ({resp.model})"
                elif listing_slow:
                    status = "OK (models listing slow, ping OK)"
                elif model_found:
                    status = "OK"
                else:
                    status = "OK (model responded but not in /models list)"
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


# -- bridge-status ----------------------------------------------------------


@cli.command("bridge-status")
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def bridge_status_cmd(ctx: click.Context, as_json: bool) -> None:
    """Diagnostic: show surgery bridge routing, version, and call counters.

    Reports which execution path (direct import vs subprocess) is active,
    plugin version compatibility, and cumulative call/fallback/error stats.
    Designed for both human operators and programmatic health checks.
    """
    # Import bridge from the ecosystem (memory/ dir in superrepo)
    # or provide a standalone fallback for users without the superrepo.
    status: dict | None = None

    try:
        from memory.surgery_bridge import bridge_status  # type: ignore
        status = bridge_status()
    except ImportError:
        # Standalone mode: report what we can from this side
        import shutil as _shutil
        cli_path = _shutil.which("3s")
        try:
            import importlib.metadata
            ver = importlib.metadata.version("three-surgeons")
        except Exception:
            ver = None

        status = {
            "mode": "(bridge not installed — standalone plugin)",
            "effective_route": "direct (plugin-native)",
            "direct_import_available": True,
            "cli_available": cli_path is not None,
            "cli_path": cli_path,
            "plugin_version": ver,
            "expected_version": ver,
            "version_compatible": True,
            "version_detail": "standalone — no bridge version check needed",
            "counters": {"note": "counters available only via bridge"},
        }

    # QQ1 2026-05-08 — attach neurologist fallback chain counters so
    # programmatic health checks (Atlas, fleet dashboards) see them too.
    try:
        from three_surgeons.core.config import get_neuro_fallback_counters
        status["neuro_fallback_counters"] = get_neuro_fallback_counters()
    except Exception:  # noqa: BLE001 — diagnostic, never crash
        status["neuro_fallback_counters"] = {}

    if as_json:
        click.echo(json.dumps(status, indent=2, default=str))
        return

    # Human-readable output
    click.echo("Surgery Bridge Status")
    click.echo("=" * 40)
    click.echo(f"  Mode:            {status['mode']}")
    click.echo(f"  Effective route: {status['effective_route']}")
    click.echo(f"  Direct import:   {'yes' if status['direct_import_available'] else 'no'}")
    cli_info = status.get('cli_path') or 'not found'
    click.echo(f"  3s CLI:          {'yes' if status.get('cli_available') else 'no'} ({cli_info})")

    click.echo()
    pv = status.get('plugin_version') or 'unknown'
    click.echo(f"  Plugin version:  {pv}")
    vc = status.get('version_compatible')
    if vc is True:
        click.echo(f"  Version check:   OK")
    elif vc is False:
        click.echo(f"  Version check:   MISMATCH — {status.get('version_detail', '')}")
    else:
        click.echo(f"  Version check:   skipped (version not detectable)")

    counters = status.get("counters", {})
    if counters and counters.get("note") is None:
        click.echo()
        click.echo("  Counters (this process):")
        click.echo(f"    Direct calls:    {counters.get('direct_calls', 0)}")
        click.echo(f"    Subprocess calls:{counters.get('subprocess_calls', 0)}")
        click.echo(f"    Fallbacks:       {counters.get('fallbacks', 0)}")
        click.echo(f"    Errors:          {counters.get('errors', 0)}")

    # QQ3 — surface diversity-canary counters as a sidecar block.
    try:
        from three_surgeons.core.diversity_canary import get_diversity_status
        dstat = get_diversity_status()
        dctr = dstat.get("counters", {})
        click.echo()
        enabled = "yes" if dstat.get("enabled") else "no (kill-switch)"
        click.echo(f"  Diversity canary: {enabled}")
        click.echo(f"    Consensus calls:        {dctr.get('consensus_total', 0)}")
        click.echo(f"    YELLOW signals total:   {dctr.get('yellow_signals_total', 0)}")
    except Exception:  # noqa: BLE001 — ZSF: bridge-status must not regress
        pass

    # QQ1 2026-05-08 — neurologist fallback chain observability. Counts
    # increment per-process whenever Config.discover() walks the chain.
    try:
        from three_surgeons.core.config import get_neuro_fallback_counters
        nfc = get_neuro_fallback_counters()
        # Inject into JSON output too — re-render if --json-output was set.
        if any(v for v in nfc.values()):
            click.echo()
            click.echo("  Neurologist fallback chain (this process):")
            for key in ("ollama", "mlx", "mlx_proxy", "deepseek",
                        "default_kept", "no_provider_reachable"):
                click.echo(f"    {key:<22} {nfc.get(key, 0)}")
    except Exception:  # noqa: BLE001 — diagnostic command, never crash
        pass

    # Exit 1 if version mismatch
    if vc is False:
        ctx.exit(1)


# -- setup-check ------------------------------------------------------------


@cli.command("setup-check")
@click.pass_context
def setup_check(ctx: click.Context) -> None:
    """Non-interactive setup diagnostic for coding agents and CI.

    Checks: config discovery, API keys, local backends, endpoint connectivity.
    Returns JSON-like summary suitable for agent consumption.
    """
    import json as _json

    from three_surgeons.core.config import detect_local_backend

    config: Config = ctx.obj["config"]
    results: dict = {"config_source": "defaults", "surgeons": {}, "local_backends": []}

    # Config source
    config_path = Path.home() / ".3surgeons" / "config.yaml"
    project_path = Path.cwd() / ".3surgeons.yaml"
    if project_path.is_file():
        results["config_source"] = str(project_path)
    elif config_path.is_file():
        results["config_source"] = str(config_path)

    # Local backend detection
    backends = detect_local_backend(timeout_s=2.0)
    results["local_backends"] = [
        {"provider": b["provider"], "port": b["port"], "models": b["models"][:3]}
        for b in backends
    ]

    # Check each surgeon
    for name, surgeon_cfg in [
        ("cardiologist", config.cardiologist),
        ("neurologist", config.neurologist),
    ]:
        is_local = surgeon_cfg.provider in ("ollama", "mlx", "local", "vllm", "lmstudio")
        info: dict = {
            "provider": surgeon_cfg.provider,
            "endpoint": surgeon_cfg.endpoint,
            "model": surgeon_cfg.model,
            "is_local": is_local,
            "api_key_set": bool(surgeon_cfg.get_api_key()) if not is_local else True,
            "api_key_env": surgeon_cfg.api_key_env if not is_local else "",
            "reachable": False,
            "ping_ok": False,
        }

        # Connectivity check
        try:
            import httpx
            resp = httpx.get(f"{surgeon_cfg.endpoint.rstrip('/')}/models", timeout=3.0)
            info["reachable"] = resp.status_code == 200
        except Exception:
            pass

        # Ping check (only if reachable and key is available)
        if info["reachable"] and (is_local or info["api_key_set"]):
            try:
                provider = LLMProvider(surgeon_cfg)
                ping = provider.ping(timeout_s=10.0)
                info["ping_ok"] = ping.ok
                if ping.ok:
                    info["ping_latency_ms"] = ping.latency_ms
            except Exception:
                pass

        results["surgeons"][name] = info

    # Summary
    all_ok = all(s["ping_ok"] for s in results["surgeons"].values())
    results["status"] = "operational" if all_ok else "degraded"

    # Structured diagnostics
    from three_surgeons.core.diagnostics import run_all_checks
    diag_results = run_all_checks()
    results["diagnostics"] = [r.to_dict() for r in diag_results]

    click.echo(_json.dumps(results, indent=2))

    if not all_ok:
        click.echo("\n--- Setup guidance ---", err=True)
        for name, info in results["surgeons"].items():
            if not info["ping_ok"]:
                if not info["api_key_set"] and not info["is_local"]:
                    click.echo(
                        f"  {name}: Set {info['api_key_env']} env var "
                        f"(provider: {info['provider']})",
                        err=True,
                    )
                elif not info["reachable"]:
                    click.echo(
                        f"  {name}: Start {info['provider']} server or check endpoint "
                        f"({info['endpoint']})",
                        err=True,
                    )
                else:
                    click.echo(
                        f"  {name}: Endpoint reachable but query failed. "
                        f"Check model '{info['model']}' availability.",
                        err=True,
                    )
        if not results["local_backends"]:
            click.echo(
                "\n  No local LLM detected. Supported: mlx_lm.server (5044), "
                "Ollama (11434), LM Studio (1234), vLLM (8000)",
                err=True,
            )
        click.echo("\n  Run '3s init' for interactive setup.", err=True)
        ctx.exit(1)


# -- doctor -----------------------------------------------------------------


@cli.command()
@click.option("--json", "json_mode", is_flag=True, help="Output structured JSON")
@click.option("--probe", is_flag=True, help="Run ecosystem probe and show detected phase")
@click.option("--history", is_flag=True, help="Show upgrade event log")
@click.option("--revert", is_flag=True, help="Revert to last stable phase")
@click.option("--upgrade", "do_upgrade", is_flag=True, help="Run integration depth chooser")
@click.pass_context
def doctor(ctx: click.Context, json_mode: bool, probe: bool, history: bool, revert: bool, do_upgrade: bool) -> None:
    """Diagnose installation health with structured 3S-* error codes.

    Checks Python version, MCP runtime, config files, and local backends,
    and skill registration. Manages upgrade lifecycle.
    """
    import json as _json

    config = ctx.obj["config"]
    config_dir = Path.home() / ".3surgeons"

    if probe:
        from three_surgeons.core.upgrade import EcosystemProbe
        prober = EcosystemProbe()
        result = prober.run()
        click.echo(f"Current phase: {config.phase}")
        click.echo(f"Detected phase: {result.detected_phase}")
        click.echo(f"Capabilities: {', '.join(c.value for c in result.capabilities) or 'none'}")
        if result.details:
            for k, v in result.details.items():
                click.echo(f"  {k}: {v}")
        return

    if history:
        from three_surgeons.core.upgrade import UpgradeEventLog
        log = UpgradeEventLog(config_dir / "upgrade.log")
        entries = log.read_all()
        if not entries:
            click.echo("No upgrade history.")
            return
        click.echo("Upgrade History")
        click.echo("=" * 40)
        for entry in entries:
            ts = entry.get("timestamp", "?")
            event = entry.get("event", "?")
            detail = entry.get("details", "")
            phases = ""
            if "from_phase" in entry:
                phases = f" (Phase {entry['from_phase']} -> {entry.get('to_phase', '?')})"
            click.echo(f"  [{ts}] {event}{phases}")
            if detail:
                click.echo(f"    {detail}")
        return

    if revert:
        from three_surgeons.core.upgrade import TransactionStatus, UpgradeEventLog, UpgradeTransaction
        tx = UpgradeTransaction(config_dir)
        if tx.status == TransactionStatus.COMMITTED:
            tx.rollback()
            event_log = UpgradeEventLog(config_dir / "upgrade.log")
            event_log.record("revert", details="Manual revert via doctor --revert")
            click.echo("Reverted to previous phase.")
        else:
            click.echo("No committed upgrade snapshot to revert.")
            ctx.exit(1)
        return

    if do_upgrade:
        from three_surgeons.core.config_resolver import ConfigResolver
        from three_surgeons.core.chooser import choose_integration_depth

        resolver = ConfigResolver(probe=True)
        state = resolver.resolve_state()
        cdna = resolver.resolve_contextdna()

        # Capability negotiation
        caps = {}
        if cdna.enabled:
            caps = resolver.negotiate_capabilities(cdna.url) or {}

        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=(state.backend == "redis" or resolver._probe_redis()),
            contextdna_available=cdna.enabled,
        )

        if plan is None:
            click.echo("No shared backends detected. Staying on Phase 1.")
            return

        click.echo(f"\nRecommended: {plan.depth.value.upper()}")
        click.echo(f"  {plan.description}")
        click.echo(f"\nAvailable options: {', '.join(d.value for d in plan.available_depths)}")
        click.echo(f"\nConfig changes ({len(plan.config_changes)}):")
        for change in plan.config_changes:
            click.echo(f"  [{change['section']}] {change['key']} = {change['value']}")
        return

    # Default: run diagnostics
    from three_surgeons.core.diagnostics import run_all_checks

    results = run_all_checks()
    failed = [r for r in results if not r.passed]

    if json_mode:
        output = {
            "checks": [r.to_dict() for r in results],
            "all_passed": len(failed) == 0,
            "failed": [r.to_dict() for r in failed],
            "phase": config.phase,
        }
        click.echo(_json.dumps(output, indent=2))
    else:
        click.echo("3-Surgeons Doctor")
        click.echo("=" * 40)
        for r in results:
            icon = "PASS" if r.passed else "FAIL"
            click.echo(f"  [{icon}] {r.code.value}: {r.message}")
        click.echo()
        if failed:
            click.echo("--- Fixes ---")
            for r in failed:
                if r.fix:
                    click.echo(f"  {r.code.value}: {r.fix}")
            click.echo()

    if failed:
        ctx.exit(1)


# -- cross-exam -------------------------------------------------------------


def _print_phase_result(result: dict, phase: str) -> None:
    """Print per-surgeon results for a live surgery phase."""
    for surgeon in ("cardiologist", "neurologist"):
        data = result.get(surgeon)
        if data is None:
            click.echo(f"  [{surgeon.upper()}] unavailable", err=True)
            continue

        click.echo(f"  [{surgeon.upper()}]")

        # Findings
        findings = data.get("findings", [])
        for f in findings:
            click.echo(f"    \u2022 {f}")

        # Challenges (deepen phase)
        challenges = data.get("challenges", [])
        for c in challenges:
            click.echo(f"    \u26a1 {c}")

        # Confidence
        confidence = data.get("confidence")
        if confidence is not None:
            click.echo(f"    confidence: {confidence:.2f}")

        # Latency
        latency = data.get("latency_ms")
        if latency is not None:
            click.echo(f"    latency: {latency:.0f}ms")

    # Phase summary
    summary = result.get("phase_summary")
    if summary:
        click.echo(f"\n  Summary: {summary}")

    # Warnings
    for w in result.get("warnings", []):
        click.echo(f"  [WARNING] {w}", err=True)


@cli.command("cross-exam")
@click.argument("topic")
@click.option(
    "--mode",
    "review_mode",
    type=click.Choice(["single", "iterative", "continuous"], case_sensitive=False),
    default=None,
    help="Review loop depth: single (1 pass), iterative (up to 3), continuous (up to 5).",
)
@click.option("--files", "-f", multiple=True, help="File paths to include as context")
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.option("--live", is_flag=True, help="Phased execution with real-time progress output")
@click.pass_context
def cross_exam(ctx: click.Context, topic: str, review_mode: Optional[str], files: tuple, dry_run: bool, live: bool) -> None:
    """Full cross-examination protocol."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("cross_examine", {"topic": topic, "review_mode": review_mode, "files": list(files)})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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

    file_paths = list(files) if files else None

    if live:
        from three_surgeons.core.sessions import SessionManager

        sessions = SessionManager()
        session = sessions.create(
            topic=topic, mode=mode.value, depth="full", file_paths=file_paths or [],
        )

        click.echo("\u2550" * 48)
        click.echo("  LIVE SURGERY \u2014 Cross-Examination")
        click.echo(f'  Topic: "{topic}"')
        click.echo(f"  Mode: {mode.value} (up to {mode.max_iterations} rounds)")
        click.echo("\u2550" * 48)
        click.echo()

        iteration = 0
        result = {}
        for iteration in range(1, mode.max_iterations + 1):
            if iteration > 1:
                result = team.phase_iterate(session)
                sessions.save(session)
                click.echo(f"\n--- Round {iteration} ---\n")

            # Phase 1: Start
            click.echo("Phase 1: Independent Analysis...")
            result = team.phase_start(session)
            sessions.save(session)
            _print_phase_result(result, "start")

            # Phase 2: Deepen
            click.echo("\nPhase 2: Cross-Review...")
            result = team.phase_deepen(session)
            sessions.save(session)
            _print_phase_result(result, "deepen")

            # Phase 3: Explore
            click.echo("\nPhase 3: Open Exploration...")
            result = team.phase_explore(session)
            sessions.save(session)
            _print_phase_result(result, "explore")

            # Phase 4: Synthesize
            click.echo("\nPhase 4: Synthesis...")
            result = team.phase_synthesize(session)
            sessions.save(session)
            _print_phase_result(result, "synthesize")

            # Check next action
            next_action = result.get("next_action", "done")
            if next_action == "done":
                break

        # Print consensus box
        scores = result.get("consensus_scores", session.consensus_scores)
        final_score = scores[-1] if scores else 0.0
        click.echo()
        click.echo("\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510")
        click.echo(f"\u2502  CONSENSUS \u2014 Round {iteration:<15}\u2502")
        click.echo(f"\u2502  Score: {final_score:.2f} / 0.70 threshold    \u2502")
        click.echo(f"\u2502  Status: {'REACHED' if final_score >= 0.7 else 'NOT REACHED':<21}\u2502")
        click.echo(f"\u2502  Cost: ${session.total_cost:.4f}               \u2502")
        click.echo("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518")

        sessions.delete(session.session_id)  # Clean up after completion
        return

    click.echo(f"Cross-examining ({mode.value} mode, max {mode.max_iterations} iterations): {topic}\n")
    result = team.cross_examine_iterative(topic, mode=mode, file_paths=file_paths)

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
@click.option("--files", "-f", multiple=True, help="File paths to include as context")
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def consult(ctx: click.Context, topic: str, files: tuple, dry_run: bool) -> None:
    """Quick consult with both surgeons."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("consult", {"topic": topic, "files": list(files)})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = _make_neuro(config)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    file_paths = list(files) if files else None
    click.echo(f"Consulting on: {topic}\n")
    result = team.consult(topic, file_paths=file_paths)

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.option(
    "--counter-probe",
    is_flag=True,
    help=(
        "SS1 sycophancy gate: also probe the claim's negation; demote score "
        "to 0.0 if both surgeons agree with BOTH directions at conf>=0.7. "
        "Costs ~2x normal consensus. Env: CONTEXT_DNA_CONSENSUS_COUNTER_PROBE=on."
    ),
)
@click.pass_context
def consensus(ctx: click.Context, claim: str, dry_run: bool, counter_probe: bool) -> None:
    """Confidence-weighted consensus on a claim."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("consensus", {"claim": claim})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    from three_surgeons.core.cross_exam import SurgeryTeam
    from three_surgeons.core.counter_probe import is_enabled as _cp_enabled

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = _make_neuro(config)
    team = SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )

    counter_probe_active = _cp_enabled(counter_probe)
    click.echo(f"Consensus on: {claim}\n")
    if counter_probe_active:
        click.echo("  Counter-probe gate: ON (will probe negation)")
    result = team.consensus(claim, counter_probe=counter_probe_active)

    click.echo(f"  Cardiologist: {result.cardiologist_assessment} "
               f"(confidence={result.cardiologist_confidence:.2f})")
    click.echo(f"  Neurologist:  {result.neurologist_assessment} "
               f"(confidence={result.neurologist_confidence:.2f})")
    click.echo(f"  Weighted score: {result.weighted_score:+.2f}")
    click.echo(f"  Total cost: ${result.total_cost:.4f}")

    # Counter-probe verdict (SS1). Only print when the gate actually ran.
    if getattr(result, "counter_probe_active", False):
        click.echo()
        click.echo(
            f"  Counter-probe negation score: "
            f"{result.counter_probe_negation_score:+.2f}"
        )
        click.echo(
            f"  Counter-probe cost:           ${result.counter_probe_cost:.4f}"
        )
        if result.sycophantic:
            click.echo(
                f"  Verdict: NO-GENUINE-CONSENSUS (sycophantic) — "
                f"effective score demoted from "
                f"{result.weighted_score:+.2f} to {result.effective_score:+.2f}"
            )
            click.echo(f"  Reason: {result.counter_probe_reason}", err=True)
        elif result.counter_probe_genuine:
            click.echo(
                f"  Verdict: GENUINE — effective score {result.effective_score:+.2f} "
                f"(both surgeons distinguished claim from negation)"
            )
        elif result.counter_probe_single_flip:
            click.echo(
                f"  Verdict: PARTIAL — effective score {result.effective_score:+.2f} "
                f"(only one surgeon flipped; confidence reduced)"
            )
            click.echo(f"  Reason: {result.counter_probe_reason}", err=True)
        else:
            click.echo(
                f"  Verdict: NO-SIGNAL — effective score {result.effective_score:+.2f}"
            )
        # Cost-cap warning (single-call cap is $0.05).
        if result.total_cost > 0.05:
            click.echo(
                f"  ⚠️  Counter-probe combined cost ${result.total_cost:.4f} "
                f"exceeds $0.05 single-call cap.",
                err=True,
            )

    # QQ3 diversity canary — stderr-only so machine-parseable stdout stays
    # clean. Aaron greps for the warning; agents parsing stdout don't see it.
    if getattr(result, "diversity_yellow", False):
        for reason in getattr(result, "diversity_reasons", []) or []:
            click.echo(f"\n  ⚠️  Diversity canary: {reason}", err=True)


# -- diversity-status -------------------------------------------------------


@cli.command("diversity-status")
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def diversity_status_cmd(ctx: click.Context, as_json: bool) -> None:
    """Diagnostic: show diversity-canary counters (QQ3).

    Sidecar to INV-006 — surfaces YELLOW collapse signals (model collapse,
    byte-identical replies, frictionless agreement) without failing
    consensus. Set ``CONTEXT_DNA_DIVERSITY_CANARY=off`` to disable emission.
    """
    from three_surgeons.core.diversity_canary import get_diversity_status

    status = get_diversity_status()
    if as_json:
        click.echo(json.dumps(status, indent=2, default=str))
        return

    click.echo("Diversity Canary Status")
    click.echo("=" * 40)
    enabled = "yes" if status["enabled"] else "no (kill-switch active)"
    click.echo(f"  Enabled: {enabled}")
    click.echo()
    click.echo("  Counters (this process):")
    counters = status["counters"]
    click.echo(f"    Consensus calls:           {counters.get('consensus_total', 0)}")
    click.echo(f"    Same provider+model:       {counters.get('same_provider_same_model', 0)}")
    click.echo(f"    Byte-identical replies:    {counters.get('byte_identical_replies', 0)}")
    click.echo(f"    Frictionless agree:        {counters.get('verdict_agree_no_caveats', 0)}")
    click.echo(f"    Total YELLOW signals:      {counters.get('yellow_signals_total', 0)}")


# -- sentinel ---------------------------------------------------------------


@cli.command("sentinel")
@click.argument("content")
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def sentinel_run(ctx: click.Context, content: str, dry_run: bool) -> None:
    """Run complexity vector sentinel."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("sentinel_run", {"content": content})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def gains_gate(ctx: click.Context, dry_run: bool) -> None:
    """Run gains gate verification."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("gains_gate", {})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
@click.option("--files", "-f", multiple=True, help="File paths to include as context")
@click.option("--rounds", "-r", default=1, type=int, help="Number of iterative rounds (1-3)")
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def neurologist_challenge_cmd(ctx: click.Context, topic: str, files: tuple, rounds: int, dry_run: bool) -> None:
    """Corrigibility skeptic challenge on a topic."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("neurologist_challenge", {"topic": topic, "files": list(files), "rounds": rounds})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    from three_surgeons.core.neurologist import neurologist_challenge

    config: Config = ctx.obj["config"]
    neuro = _make_neuro(config)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    file_paths = list(files) if files else None

    click.echo(f"Challenging: {topic}\n")

    if rounds > 1:
        from three_surgeons.core.neurologist import neurologist_challenge_iterative

        result = neurologist_challenge_iterative(
            topic, neuro, evidence_store=evidence,
            file_paths=file_paths, rounds=min(rounds, 3),
        )
        click.echo(f"Iterations: {result.iteration_count}")
    else:
        result = neurologist_challenge(topic, neuro, evidence_store=evidence, file_paths=file_paths)

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def ask_local_cmd(ctx: click.Context, prompt: str, dry_run: bool) -> None:
    """Direct query to the neurologist (local model)."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("ask_local", {"prompt": prompt})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def ask_remote_cmd(ctx: click.Context, prompt: str, dry_run: bool) -> None:
    """Direct query to the cardiologist (remote model)."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("ask_remote", {"prompt": prompt})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
@click.option("--files", "-f", multiple=True, help="File paths to include as context")
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def cardio_review_cmd(ctx: click.Context, topic: str, git_context: str, files: tuple, dry_run: bool) -> None:
    """Cardiologist cross-examination review."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("cardio_review", {"topic": topic, "git_context": git_context, "files": list(files)})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    from three_surgeons.core.cardio import cardio_review
    from three_surgeons.core.cross_exam import SurgeryTeam

    config: Config = ctx.obj["config"]
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    cardio = LLMProvider(config.cardiologist)
    neuro = _make_neuro(config)
    team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state)

    file_paths = list(files) if files else None
    click.echo(f"Cardio review: {topic}\n")
    result = cardio_review(topic, team, evidence_store=evidence, git_context=git_context, file_paths=file_paths)

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def research_cmd(ctx: click.Context, topic: str, dry_run: bool) -> None:
    """Self-directed research on a topic."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("research", {"topic": topic})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
@click.option("--dry-run", is_flag=True, help="Show what would happen without executing")
@click.pass_context
def ab_propose(
    ctx: click.Context,
    param: str,
    variant_a: str,
    variant_b: str,
    hypothesis: str,
    dry_run: bool,
) -> None:
    """Propose an A/B test."""
    if dry_run:
        from three_surgeons.core.dry_run import check_dry_run
        result = check_dry_run("ab_propose", {"param": param, "variant_a": variant_a, "variant_b": variant_b, "hypothesis": hypothesis})
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

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
    try:
        import uvicorn

        from three_surgeons.http.server import create_app
    except ImportError:
        click.echo(
            "Error: HTTP dependencies not installed. "
            "Run: pip install 'three-surgeons[http]'"
        )
        raise SystemExit(1)

    click.echo(f"3-Surgeons server starting on {host}:{port}")
    app = create_app()
    uvicorn.run(app, host=host, port=port)


# -- migrate-evidence -------------------------------------------------------


@cli.command("migrate-evidence")
@click.option("--dry-run", is_flag=True, help="Show what would migrate without executing")
@click.option("--revert", is_flag=True, help="Restore pre-migration snapshot")
@click.pass_context
def migrate_evidence(ctx: click.Context, dry_run: bool, revert: bool) -> None:
    """Migrate evidence store between phases."""
    from three_surgeons.core.migration import EvidenceMigrator

    config = ctx.obj["config"]
    db_path = config.evidence.resolved_path

    migrator = EvidenceMigrator(source_db=db_path)

    try:
        if revert:
            if migrator.revert():
                click.echo("Reverted to pre-migration snapshot.")
            else:
                click.echo("No migration snapshot found.")
                ctx.exit(1)
            return

        if dry_run:
            result = migrator.dry_run()
            click.echo(f"Evidence items: {result.total_items}")
            click.echo(f"Would migrate: {result.would_migrate}")
            return

        # Phase 1: snapshot + backup only. Phase 2 will add shared backend writes.
        result = migrator.migrate()
        click.echo(f"Migrated {result.migrated} items. Snapshot created.")
    except Exception as exc:
        click.echo(f"Migration error: {exc}", err=True)
        ctx.exit(1)


# -- capability-adaptive commands -------------------------------------------

from three_surgeons.core.context_builder import build_runtime_context
from three_surgeons.core.requirements import check_requirements, GateResult


def _run_command(ctx: click.Context, reqs, cmd_fn, **kwargs):
    """Shared runner: build context -> gate check -> execute -> format output."""
    config = ctx.obj["config"]
    runtime_ctx = build_runtime_context(config)
    gate, notes = check_requirements(reqs, runtime_ctx)

    if gate == GateResult.BLOCKED:
        click.echo("BLOCKED:", err=True)
        for note in notes:
            click.echo(f"  - {note}", err=True)
        ctx.exit(1)
        return

    result = cmd_fn(runtime_ctx, **kwargs)
    output = result.to_dict()

    if gate == GateResult.DEGRADED:
        output["degradation_notes"] = notes

    click.echo(yaml.dump(output, default_flow_style=False))


@cli.command("status")
@click.pass_context
def cmd_status_cli(ctx: click.Context) -> None:
    """System health and capability overview."""
    from three_surgeons.core.status_commands import cmd_status, STATUS_REQS
    _run_command(ctx, STATUS_REQS, cmd_status)


@cli.command("research-status")
@click.pass_context
def cmd_research_status_cli(ctx: click.Context) -> None:
    """Research budget and cost tracking."""
    from three_surgeons.core.status_commands import cmd_research_status, RESEARCH_STATUS_REQS
    _run_command(ctx, RESEARCH_STATUS_REQS, cmd_research_status)


@cli.command("ab-veto")
@click.option("--test-id", required=True, help="A/B test ID to veto")
@click.option("--reason", required=True, help="Reason for veto")
@click.pass_context
def cmd_ab_veto_cli(ctx: click.Context, test_id: str, reason: str) -> None:
    """Veto an A/B test."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_veto, AB_VETO_REQS
    _run_command(ctx, AB_VETO_REQS, cmd_ab_veto, test_id=test_id, reason=reason)


@cli.command("ab-queue")
@click.pass_context
def cmd_ab_queue_cli(ctx: click.Context) -> None:
    """List A/B tests in the queue."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_queue, AB_QUEUE_REQS
    _run_command(ctx, AB_QUEUE_REQS, cmd_ab_queue)


@cli.command("ab-start")
@click.option("--test-id", required=True, help="A/B test ID to start")
@click.option("--duration", "duration_minutes", default=30, type=int, help="Duration in minutes")
@click.pass_context
def cmd_ab_start_cli(ctx: click.Context, test_id: str, duration_minutes: int) -> None:
    """Start (activate) a proposed A/B test."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_start, AB_START_REQS
    _run_command(ctx, AB_START_REQS, cmd_ab_start, test_id=test_id, duration_minutes=duration_minutes)


@cli.command("ab-measure")
@click.option("--test-id", required=True, help="A/B test ID to measure")
@click.pass_context
def cmd_ab_measure_cli(ctx: click.Context, test_id: str) -> None:
    """Measure an active A/B test."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_measure, AB_MEASURE_REQS
    _run_command(ctx, AB_MEASURE_REQS, cmd_ab_measure, test_id=test_id)


@cli.command("ab-conclude")
@click.option("--test-id", required=True, help="A/B test ID to conclude")
@click.option("--verdict", required=True, help="Verdict (variant_a, variant_b, inconclusive)")
@click.pass_context
def cmd_ab_conclude_cli(ctx: click.Context, test_id: str, verdict: str) -> None:
    """Conclude an A/B test with a verdict."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_conclude, AB_CONCLUDE_REQS
    _run_command(ctx, AB_CONCLUDE_REQS, cmd_ab_conclude, test_id=test_id, verdict=verdict)


@cli.command("ab-collaborate")
@click.option("--topic", required=True, help="Topic for multi-surgeon collaboration")
@click.pass_context
def cmd_ab_collaborate_cli(ctx: click.Context, topic: str) -> None:
    """Multi-surgeon collaborative A/B test design."""
    from three_surgeons.core.ab_lifecycle import cmd_ab_collaborate, AB_COLLABORATE_REQS
    _run_command(ctx, AB_COLLABORATE_REQS, cmd_ab_collaborate, topic=topic)


@cli.command("research-evidence")
@click.option("--topic", required=True, help="Topic to cross-check evidence for")
@click.pass_context
def cmd_research_evidence_cli(ctx: click.Context, topic: str) -> None:
    """Cross-check evidence store with LLM analysis."""
    from three_surgeons.core.audit_commands import cmd_research_evidence, RESEARCH_EVIDENCE_REQS
    _run_command(ctx, RESEARCH_EVIDENCE_REQS, cmd_research_evidence, topic=topic)


@cli.command("cardio-reverify")
@click.option("--topic", required=True, help="Topic to reverify evidence for")
@click.pass_context
def cmd_cardio_reverify_cli(ctx: click.Context, topic: str) -> None:
    """Multi-surgeon reverification of evidence."""
    from three_surgeons.core.audit_commands import cmd_cardio_reverify, CARDIO_REVERIFY_REQS
    _run_command(ctx, CARDIO_REVERIFY_REQS, cmd_cardio_reverify, topic=topic)


@cli.command("deep-audit")
@click.option("--topic", required=True, help="Topic for deep audit")
@click.option("--files", default=None, help="Comma-separated file paths to audit (skips LLM file selection)")
@click.pass_context
def cmd_deep_audit_cli(ctx: click.Context, topic: str, files: str | None) -> None:
    """5-phase chained deep audit pipeline."""
    from three_surgeons.core.audit_commands import cmd_deep_audit, DEEP_AUDIT_REQS
    file_paths = [f.strip() for f in files.split(",") if f.strip()] if files else None
    _run_command(ctx, DEEP_AUDIT_REQS, cmd_deep_audit, topic=topic, file_paths=file_paths)


# -- chain orchestration --------------------------------------------------------


@cli.group("chain", invoke_without_command=True)
@click.pass_context
def chain_group(ctx: click.Context) -> None:
    """Chain orchestration — composable multi-step surgical workflows."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@chain_group.command("run")
@click.option("--mode", required=True, help="Preset name (full-3s, lightweight, plan-review, evidence-dive)")
@click.option("--topic", default="", help="Topic for the chain execution")
@click.pass_context
def chain_run(ctx: click.Context, mode: str, topic: str) -> None:
    """Execute a chain preset."""
    from three_surgeons.core.chains import ChainExecutor, SEGMENT_REGISTRY
    from three_surgeons.core.mode_authority import ModeAuthority

    config = ctx.obj["config"]
    runtime_ctx = build_runtime_context(config)
    state = runtime_ctx.state

    ma = ModeAuthority(state)
    try:
        segments = ma.resolve(mode, {})
    except KeyError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        ctx.exit(1)
        return

    # Check which segments are actually registered
    missing = [s for s in segments if s not in SEGMENT_REGISTRY]
    if missing:
        click.echo(f"WARNING: Unregistered segments (will be skipped): {missing}", err=True)
        segments = [s for s in segments if s in SEGMENT_REGISTRY]

    if not segments:
        click.echo("No registered segments to run.", err=True)
        ctx.exit(1)
        return

    executor = ChainExecutor(state_backend=state)
    result = executor.run(segments, runtime_ctx, initial_data={"topic": topic})

    output = {
        "mode": mode,
        "segments_run": list(result.segment_results.keys()),
        "segments_skipped": [s[0] for s in result.skipped],
        "segments_degraded": [s[0] for s in result.degraded],
        "errors": [{"segment": s, "error": e} for s, e in result.errors],
        "halted": result.halted,
        "duration_ms": result.total_ns / 1_000_000,
        "success": len(result.errors) == 0 and not result.halted,
    }
    click.echo(yaml.dump(output, default_flow_style=False))


@chain_group.command("presets")
@click.pass_context
def chain_presets(ctx: click.Context) -> None:
    """List all available chain presets."""
    from three_surgeons.core.mode_authority import PRESETS

    click.echo("Available chain presets:\n")
    for name, segments in PRESETS.items():
        click.echo(f"  {name}:")
        for seg in segments:
            click.echo(f"    - {seg}")
        click.echo()


@chain_group.command("suggest")
@click.option("--trigger", default="", help="Trigger type to check")
@click.pass_context
def chain_suggest(ctx: click.Context, trigger: str) -> None:
    """Show available mode suggestions based on context."""
    from three_surgeons.core.mode_authority import ModeAuthority

    config = ctx.obj["config"]
    runtime_ctx = build_runtime_context(config)
    state = runtime_ctx.state

    ma = ModeAuthority(state)
    suggestion = ma.suggest(runtime_ctx, trigger)

    if suggestion:
        click.echo(f"Suggestion: {suggestion.message}")
        click.echo(f"  Mode: {suggestion.mode}")
        click.echo(f"  Trigger: {suggestion.trigger}")
    else:
        click.echo("No suggestions for current context.")


@chain_group.command("history")
@click.option("--chain-id", default="", help="Filter by chain ID")
@click.option("--limit", default=10, help="Number of recent executions")
@click.pass_context
def chain_history(ctx: click.Context, chain_id: str, limit: int) -> None:
    """Show recent chain executions."""
    from three_surgeons.core.chain_telemetry import ChainTelemetry

    config = ctx.obj["config"]
    runtime_ctx = build_runtime_context(config)

    tel = ChainTelemetry(runtime_ctx.state)
    if chain_id:
        execs = tel.recent_executions(chain_id, limit=limit)
    else:
        # Show all chains
        execs = []
        for preset in ["full-3s", "lightweight", "plan-review", "evidence-dive"]:
            execs.extend(tel.recent_executions(preset, limit=limit))

    if not execs:
        click.echo("No chain executions recorded yet.")
        return

    for rec in execs:
        status = "OK" if rec.success else "FAIL"
        click.echo(
            f"  [{status}] {rec.chain_id} "
            f"({len(rec.segments_run)} segments, {rec.duration_ms:.0f}ms)"
        )


@chain_group.command("telemetry")
@click.pass_context
def chain_telemetry(ctx: click.Context) -> None:
    """Show learning stats — patterns, dependencies, confidence."""
    from three_surgeons.core.chain_telemetry import ChainTelemetry

    config = ctx.obj["config"]
    runtime_ctx = build_runtime_context(config)

    tel = ChainTelemetry(runtime_ctx.state)
    click.echo("Pattern detection results:\n")
    for preset in ["full-3s", "lightweight", "plan-review", "evidence-dive"]:
        patterns = tel.detect_patterns(preset)
        if patterns:
            click.echo(f"  {preset}:")
            for p in patterns:
                click.echo(
                    f"    {p.grade.value} ({p.observations} obs, "
                    f"{p.frequency:.0%} freq): {' -> '.join(p.segments)}"
                )
    click.echo("\nDone.")


# -- main entry point -------------------------------------------------------


def main() -> None:
    """Entry point for the 3s console script."""
    cli()


if __name__ == "__main__":
    main()
