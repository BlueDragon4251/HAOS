#!/usr/bin/env bash
# Image build only: frozen upstream dependencies and an immutable Python/runtime tree.
set -euo pipefail
cd /usr/lib/haos/hermes
test -f uv.lock
test -f .herald-os-upstream-sha
export UV_CACHE_DIR=/tmp/haos-uv-cache
export UV_PROJECT_ENVIRONMENT=/usr/lib/haos/hermes/.venv
HAOS_RUNTIME_OVERLAY=/tmp/herald-os/linux/haos/runtime
python3 "$HAOS_RUNTIME_OVERLAY/prepare.py" /usr/lib/haos/hermes "$HAOS_RUNTIME_OVERLAY"
# The Fedora Python 3.11 RPM lives in immutable /usr. Do not depend on uv's
# embedded download catalogue or silently choose Fedora's incompatible 3.14.
uv sync --frozen --python /usr/bin/python3.11 --no-python-downloads --no-dev --extra web --extra messaging
uv pip install --python .venv/bin/python --require-hashes --no-deps -r "$HAOS_RUNTIME_OVERLAY/requirements.txt"
uv pip check --python .venv/bin/python
mkdir -p /usr/lib/haos/runtime-provenance
cp "$HAOS_RUNTIME_OVERLAY/source.json" "$HAOS_RUNTIME_OVERLAY/requirements.txt" /usr/lib/haos/runtime-provenance/
uv pip freeze --python .venv/bin/python > /usr/lib/haos/runtime-provenance/installed.txt
test -x .venv/bin/hermes
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
.venv/bin/python -I -c 'import importlib.metadata,json;from pathlib import Path;s=json.loads(Path("/usr/lib/haos/runtime-provenance/source.json").read_text());assert all(importlib.metadata.version(n)==v for n,v in s["security_versions"].items())'
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_backend.py" .venv/bin/hermes /usr/lib/haos/runtime-provenance/backend-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_gateway.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/gateway-build-probe.json
rpm -q python3.11 python3.11-libs > /usr/lib/haos/python-runtime.txt
