#!/usr/bin/env bash
# Run the hermes-os-bridge plugin tests with the Hermes runtime's Python so the plugin is
# exercised against the same interpreter and dependencies the gateway loads it with.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY="${HERMES_OS_PYTHON:-$HERMES_HOME/hermes-agent/venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "test-bridge: no Hermes venv python at $PY (set HERMES_OS_PYTHON)" >&2
  exit 1
fi

cd "$ROOT/plugins/hermes-os-bridge"
exec "$PY" -m pytest -q "$@"
