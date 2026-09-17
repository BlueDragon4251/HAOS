#!/usr/bin/env bash
# Run the hermes-os-bridge plugin tests.
# Prefers the Hermes runtime's venv when it has pytest (same interpreter the gateway loads the plugin
# with); otherwise runs in an ephemeral uv environment so the user's Hermes venv is never modified.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY="${HERMES_OS_PYTHON:-$HERMES_HOME/hermes-agent/venv/bin/python}"

cd "$ROOT/plugins/tests"

if [[ -x "$PY" ]] && "$PY" -c "import pytest" >/dev/null 2>&1; then
  exec "$PY" -m pytest -q "$@"
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --python 3.11 --with pytest --with pyyaml python -m pytest -q "$@"
fi

echo "test-bridge: need either pytest in $PY or uv on PATH" >&2
exit 1
