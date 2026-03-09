#!/usr/bin/env bash
# Smoke tests for the MCP launcher's structured error output.
# Run: bash tests/test_launcher.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SCRIPT_DIR}/../bin/3surgeons-mcp"
PASS=0; FAIL=0

assert_contains() {
    local label="$1" output="$2" expected="$3"
    if echo "$output" | grep -q "$expected"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label — expected '$expected' in output"
        ((FAIL++)) || true
    fi
}

echo "=== MCP Launcher Smoke Tests ==="

# Test: launcher outputs 3S- error code when no runtime found
# Use a PATH with only basic utils (no python) to force the no-runtime path
OUTPUT=$(PATH=/usr/bin:/bin HOME=/nonexistent "$LAUNCHER" 2>&1 || true)
assert_contains "error code in output" "$OUTPUT" "3S-"

# Test: launcher script is executable
if [ -x "$LAUNCHER" ]; then
    echo "  PASS: launcher is executable"
    ((PASS++)) || true
else
    echo "  FAIL: launcher not executable"
    ((FAIL++)) || true
fi

echo
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
