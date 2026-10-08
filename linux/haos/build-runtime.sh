#!/usr/bin/env bash
# Image build only: frozen upstream dependencies and an immutable Python/runtime tree.
set -euo pipefail
cd /usr/lib/haos/hermes
test -f uv.lock
test -f .herald-os-upstream-sha
export UV_CACHE_DIR=/tmp/haos-uv-cache
export UV_PROJECT_ENVIRONMENT=/usr/lib/haos/hermes/.venv
# The Fedora Python 3.11 RPM lives in immutable /usr. Do not depend on uv's
# embedded download catalogue or silently choose Fedora's incompatible 3.14.
uv sync --frozen --python /usr/bin/python3.11 --no-python-downloads --no-dev --extra web --extra messaging
test -x .venv/bin/hermes
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
rpm -q python3.11 python3.11-libs > /usr/lib/haos/python-runtime.txt
