#!/usr/bin/env bash
set -euo pipefail
HAOS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HAOS_ROOT"
if [[ -n "${HAOS_TEST_PYTHON:-}" ]]; then
  exec "$HAOS_TEST_PYTHON" -m pytest -q linux/haos/tests "$@"
fi
exec uv run --no-project --python 3.11 --with pytest==9.0.2 --with websockets==15.0.1 python -m pytest -q linux/haos/tests "$@"
