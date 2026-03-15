"""Background adaptive poller — runs ecosystem probes during HTTP server lifecycle.

Wires AdaptivePoller + EcosystemProbe + UpgradeEngine into an asyncio task
that runs as long as the server is alive.  Probe interval adapts: starts at
5 min, backs off to 1 hr when stable, resets on any change.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".3surgeons"


async def _poll_loop() -> None:
    """Periodically probe the ecosystem and apply upgrades/downgrades."""
    from three_surgeons.core.config import Config
    from three_surgeons.core.upgrade import (
        AdaptivePoller,
        EcosystemProbe,
        UpgradeAction,
        UpgradeEngine,
    )

    poller = AdaptivePoller()
    probe = EcosystemProbe()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = Config.discover()
    engine = UpgradeEngine(config, CONFIG_DIR)

    if engine.recovered_from_crash:
        logger.warning("Recovered from interrupted upgrade — reverted to phase %d", config.phase)

    logger.info(
        "Background poller started (phase=%d, interval=%ds)",
        config.phase, int(poller.current_interval),
    )

    while True:
        try:
            if poller.should_probe():
                poller.mark_probed()
                result = probe.run()
                action, details = engine.decide(result)

                if action == UpgradeAction.NO_ACTION:
                    poller.on_no_change()
                    logger.debug(
                        "No change (phase=%d, next in %ds)",
                        config.phase, int(poller.current_interval),
                    )
                elif action in (UpgradeAction.SILENT_UPGRADE, UpgradeAction.SILENT_DOWNGRADE):
                    target = details["target_phase"]
                    label = "Upgrading" if action == UpgradeAction.SILENT_UPGRADE else "Downgrading"
                    logger.info("%s phase %d → %d", label, config.phase, target)
                    engine.execute_upgrade(target)
                    poller.on_change_detected()
                elif action == UpgradeAction.INTERACTIVE_CHOOSER:
                    # Log but don't auto-choose — user can run `3s upgrade-probe`
                    logger.info(
                        "Multiple Phase 2 backends available (%s) — run `3s upgrade-probe` to choose",
                        ", ".join(details.get("options", [])),
                    )
                    poller.on_no_change()

            await asyncio.sleep(min(poller.current_interval, 60))
        except asyncio.CancelledError:
            logger.info("Background poller stopping")
            return
        except Exception:
            logger.error("Background poller error", exc_info=True)
            await asyncio.sleep(60)
