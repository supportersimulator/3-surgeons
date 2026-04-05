#!/usr/bin/env python3
"""Generate IDE-specific config files from plugin.json (single source of truth).

Reads .claude-plugin/plugin.json and produces:
  - .mcp.json                  (generic MCP — Claude Code, Cursor, etc.)
  - .cursor-plugin/plugin.json (Cursor agent-plugin format)
  - .vscode/mcp.json.example   (VS Code native MCP)
  - .codex/config.toml.example (Codex CLI / IDE)
  - gemini-extension.json      (Gemini CLI extension)

Run from repo root:
    python3 scripts/generate-manifests.py
    python3 scripts/generate-manifests.py --check   # verify configs are up-to-date (no writes)

No secrets. No runtime deps beyond stdlib.
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / ".claude-plugin" / "plugin.json"


def to_json(data: dict) -> str:
    """JSON with non-ASCII preserved and short arrays kept on one line."""
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    # Collapse arrays where every element is a short string onto one line
    def _collapse(m: re.Match) -> str:
        items = [s.strip() for s in m.group(1).split(",")]
        joined = ", ".join(items)
        if len(joined) < 100:
            return f"[{joined}]"
        return m.group(0)
    raw = re.sub(r'\[\s*\n((?:\s*"[^"]{0,40}",?\s*\n)+)\s*\]', _collapse, raw)
    return raw + "\n"


def load_canonical() -> dict:
    if not CANONICAL.exists():
        print(f"ERROR: canonical manifest not found: {CANONICAL}", file=sys.stderr)
        sys.exit(1)
    with open(CANONICAL) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Builders — each returns (path, expected_content)
# ---------------------------------------------------------------------------

def build_mcp_json(canon: dict) -> tuple[Path, str]:
    """Generic .mcp.json — uses ${PLUGIN_ROOT} for portability."""
    data = {
        "mcpServers": {
            "3-surgeons": {
                "command": "${PLUGIN_ROOT}/bin/3surgeons-mcp",
                "args": [],
                "tools": ["*"],
            }
        }
    }
    return ROOT / ".mcp.json", to_json(data)


def build_cursor_plugin(canon: dict) -> tuple[Path, str]:
    """Cursor agent-plugin format — skills/agents/commands/hooks + MCP ref."""
    data = {
        "name": canon["name"],
        "displayName": canon.get("displayName", "3-Surgeons"),
        "description": canon["description"],
        "version": canon["version"],
        "author": canon["author"],
        "homepage": canon["homepage"],
        "repository": canon["repository"],
        "license": canon["license"],
        "keywords": canon.get("keywords", []),
        "skills": "./skills/",
        "agents": "./agents/",
        "commands": "./commands/",
        "hooks": "./hooks/hooks.json",
        "mcp": "./.mcp.json",
    }
    return ROOT / ".cursor-plugin" / "plugin.json", to_json(data)


def build_vscode_mcp(canon: dict) -> tuple[Path, str]:
    """VS Code native MCP config example."""
    data = {
        "servers": {
            "3-surgeons": {
                "command": "${workspaceFolder}/bin/3surgeons-mcp",
                "args": [],
            }
        }
    }
    return ROOT / ".vscode" / "mcp.json.example", to_json(data)


def build_codex_config(canon: dict) -> tuple[Path, str]:
    """Codex CLI / IDE config example (TOML)."""
    content = textwrap.dedent("""\
        # Codex MCP config for 3-Surgeons
        # Copy to ~/.codex/config.toml or .codex/config.toml in your project root.
        # Replace the command path with the absolute path to your clone.
        #
        # Quick install:
        #   codex mcp add 3-surgeons -- /path/to/3-surgeons/bin/3surgeons-mcp

        [mcp_servers."3-surgeons"]
        command = "./bin/3surgeons-mcp"
        args = []
    """)
    return ROOT / ".codex" / "config.toml.example", content


def build_gemini_extension(canon: dict) -> tuple[Path, str]:
    """Gemini CLI extension manifest."""
    data = {
        "name": canon["name"],
        "version": canon["version"],
        "description": canon["description"],
        "contextFileName": "GEMINI.md",
        "mcpServers": {
            "3-surgeons": {
                "command": "${extensionPath}/bin/3surgeons-mcp",
                "args": [],
                "cwd": "${extensionPath}",
            }
        },
    }
    return ROOT / "gemini-extension.json", to_json(data)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BUILDERS = [
    build_mcp_json,
    build_cursor_plugin,
    build_vscode_mcp,
    build_codex_config,
    build_gemini_extension,
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    check_mode = "--check" in sys.argv

    canon = load_canonical()
    print(f"Canonical source: {CANONICAL.relative_to(ROOT)}")
    print(f"  name={canon['name']}  version={canon['version']}")
    print()

    drifted: list[str] = []

    for builder in BUILDERS:
        path, expected = builder(canon)
        rel = path.relative_to(ROOT)

        if check_mode:
            if not path.exists():
                print(f"  [MISSING]  {rel}")
                drifted.append(str(rel))
            elif path.read_text() != expected:
                print(f"  [DRIFTED]  {rel}")
                drifted.append(str(rel))
            else:
                print(f"  [ok]       {rel}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
            print(f"  [wrote]    {rel}")

    print()
    if check_mode:
        if drifted:
            print(f"FAIL: {len(drifted)} manifest(s) out of sync. Run without --check to fix.")
            sys.exit(1)
        else:
            print("All manifests match canonical source.")
    else:
        print(f"Generated {len(BUILDERS)} manifests from {CANONICAL.name}.")
        print("Commit these files — they should never be hand-edited.")


if __name__ == "__main__":
    main()
