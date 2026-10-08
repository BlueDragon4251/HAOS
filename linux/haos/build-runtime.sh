#!/usr/bin/env bash
# Image build only: frozen upstream dependencies and an immutable Python/runtime tree.
set -euo pipefail
cd /usr/lib/haos/hermes
test -f uv.lock
test -f .herald-os-upstream-sha
export UV_PYTHON_INSTALL_DIR=/usr/lib/haos/python
export UV_CACHE_DIR=/tmp/haos-uv-cache
export UV_PROJECT_ENVIRONMENT=/usr/lib/haos/hermes/.venv
uv sync --frozen --python 3.11.17 --no-dev --extra web --extra messaging
test -x .venv/bin/hermes
