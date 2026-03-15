"""Test background_poller wiring."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_poll_loop_cancels_cleanly():
    """Poller task handles cancellation without raising."""
    with patch("three_surgeons.core.config.Config.discover") as mock_discover, \
         patch("three_surgeons.core.upgrade.EcosystemProbe") as MockProbe, \
         patch("three_surgeons.core.upgrade.UpgradeEngine") as MockEngine:

        mock_discover.return_value = MagicMock(phase=1)
        mock_engine = MockEngine.return_value
        mock_engine.recovered_from_crash = False
        mock_engine.decide.return_value = ("no_action", {})

        mock_probe = MockProbe.return_value
        mock_probe.run.return_value = MagicMock(detected_phase=1, capabilities=[])

        from three_surgeons.http.background_poller import _poll_loop

        task = asyncio.create_task(_poll_loop())
        await asyncio.sleep(0.15)
        task.cancel()
        await asyncio.sleep(0.05)
        # Task catches CancelledError and returns cleanly
        assert task.done()
        assert mock_probe.run.called


def test_create_app_has_lifespan():
    """create_app() wires a lifespan (which starts the poller)."""
    from three_surgeons.http.server import create_app, _lifespan
    app = create_app()
    # Starlette stores lifespan on the router
    assert app.router.lifespan_context is not None
