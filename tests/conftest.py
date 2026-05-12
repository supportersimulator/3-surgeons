"""Shared pytest fixtures for 3-surgeons test suite.

Two autouse fixtures:

1. ``_allow_tmpdir_file_access`` — adds the system temp dir to
   ``THREE_SURGEONS_BASE_DIRS`` so file-access policy accepts test
   fixture files written under ``tmp_path``.

2. ``isolate_env`` — prevents cross-test pollution from:
     - shell-leaked provider routing env vars
     - real macOS keychain entries (``Context_DNA_*``)
     - user-level ``~/.3surgeons/config.yaml`` overrides

   Tests that *need* a specific value still call
   ``monkeypatch.setenv(...)`` in the test body — that override takes
   effect after the fixture runs because monkeypatch scopes per test.

   Tests that need to exercise the *real* keychain or real HOME can
   opt out by marking themselves ``@pytest.mark.real_env``.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import pytest


# Env vars that route LLM providers / control fallback logic.
# Clearing these at the start of every test guarantees a deterministic
# baseline regardless of the developer's shell or fleet-wide overrides.
_ENV_KEYS_TO_ISOLATE = (
    # Provider routing
    "CONTEXT_DNA_NEURO_PROVIDER",
    "CONTEXT_DNA_NEURO_FALLBACK_DISABLE",
    "CONTEXT_DNA_DIVERSITY_CANARY",
    "CONTEXT_DNA_CONSENSUS_COUNTER_PROBE",
    "LLM_EXTERNAL_PROVIDER",
    # API keys (project naming convention)
    "Context_DNA_OPENAI",
    "Context_DNA_Deepseek",
    "Context_DNA_Deep_Seek",
    "Context_DNA_Anthropic",
    # API keys (vendor SDK convention — get_api_key falls back to these)
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _allow_tmpdir_file_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure FileAccessPolicy permits files under the system temp dir.

    Tests use pytest's tmp_path which lives outside cwd. This fixture
    adds the real temp directory to THREE_SURGEONS_BASE_DIRS so the
    file access policy accepts test fixture files.
    """
    tmp_root = os.path.realpath(tempfile.gettempdir())
    cwd = os.getcwd()
    monkeypatch.setenv("THREE_SURGEONS_BASE_DIRS", f"{cwd}:{tmp_root}")


@pytest.fixture(autouse=True)
def isolate_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    request: pytest.FixtureRequest,
) -> None:
    """Clear 3-surgeons env vars, redirect HOME, stub macOS keychain.

    Without this fixture, ``Config.discover()`` will:
      * read ``~/.3surgeons/config.yaml`` (developer-specific provider
        choices leak in),
      * resolve API keys from the macOS keychain (real keys surface in
        tests that explicitly delete the env var to test the
        ``MissingProviderKeyError`` path).

    Tests that need real env / real keychain can opt out::

        @pytest.mark.real_env
        def test_keychain_integration(...):
            ...

    Individual tests that need a *specific* env var simply call
    ``monkeypatch.setenv(...)`` — monkeypatch fixture is function-scoped
    so per-test overrides win over this baseline clear.
    """
    if request.node.get_closest_marker("real_env"):
        return

    for key in _ENV_KEYS_TO_ISOLATE:
        monkeypatch.delenv(key, raising=False)

    # Redirect HOME → tmp_path so Path.home()/.3surgeons/config.yaml
    # cannot leak user-level overrides into Config.discover(). The
    # tmp_path is unique per test and auto-cleaned by pytest.
    monkeypatch.setenv("HOME", str(tmp_path))

    # Stub macOS `security` subprocess call used by
    # SurgeonConfig.get_api_key() as a third-tier fallback. Returning
    # rc=1 (entry not found) keeps the production code path intact
    # while preventing real keychain reads from leaking secrets into
    # tests that assert "no key available".
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, (list, tuple))
            and len(cmd) >= 2
            and cmd[0] == "security"
            and cmd[1] == "find-generic-password"
        ):
            class _R:
                returncode = 1
                stdout = ""
                stderr = "tests: keychain access stubbed by isolate_env fixture"
            return _R()
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _fake_run)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers used by ``isolate_env``."""
    config.addinivalue_line(
        "markers",
        "real_env: opt out of the autouse env-isolation fixture "
        "(test exercises real HOME, real keychain, or real shell env)",
    )
