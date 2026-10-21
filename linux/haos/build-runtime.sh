#!/usr/bin/env bash
# Image build only: frozen upstream dependencies and an immutable Python/runtime tree.
set -euo pipefail
cd /usr/lib/haos/hermes
test -f uv.lock
test -f .herald-os-upstream-sha
export UV_CACHE_DIR=/tmp/haos-uv-cache
export UV_PROJECT_ENVIRONMENT=/usr/lib/haos/hermes/.venv
HAOS_RUNTIME_OVERLAY=/tmp/herald-os/linux/haos/runtime
python3 "$HAOS_RUNTIME_OVERLAY/install_copilot.py" /usr/lib/haos/copilot
python3 "$HAOS_RUNTIME_OVERLAY/prepare.py" /usr/lib/haos/hermes "$HAOS_RUNTIME_OVERLAY"
# The Fedora Python 3.11 RPM lives in immutable /usr. Do not depend on uv's
# embedded download catalogue or silently choose Fedora's incompatible 3.14.
uv sync --frozen --python /usr/bin/python3.11 --no-python-downloads --no-dev --extra web --extra messaging --extra anthropic --extra bedrock --extra vertex --extra azure-identity
uv pip install --python .venv/bin/python --require-hashes --no-deps -r "$HAOS_RUNTIME_OVERLAY/requirements.txt"
uv pip check --python .venv/bin/python
# Fail the build on upstream registry drift. The setup process reads only this
# reviewed data snapshot; it must never import arbitrary plugins as root.
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/export_registry.py" /usr/lib/haos/hermes /tmp/haos-registry.json
cmp /tmp/haos-registry.json /usr/lib/haos/haos/hermes_registry.json
mkdir -p /usr/lib/haos/runtime-provenance
cp "$HAOS_RUNTIME_OVERLAY/source.json" "$HAOS_RUNTIME_OVERLAY/requirements.txt" /usr/lib/haos/runtime-provenance/
uv pip freeze --python .venv/bin/python > /usr/lib/haos/runtime-provenance/installed.txt
# Installed /usr is immutable and runtime bytecode writes are disabled. Compile
# actual trusted sources here instead of parsing the entire cold import graph
# under QEMU TCG at first boot. Keep the canonical CLI and health deadline intact.
.venv/bin/python -I "$HAOS_RUNTIME_OVERLAY/compile_runtime.py"
test -x .venv/bin/hermes
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
.venv/bin/python -I -c 'import importlib.metadata,json;from pathlib import Path;s=json.loads(Path("/usr/lib/haos/runtime-provenance/source.json").read_text());assert all(importlib.metadata.version(n)==v for n,v in {**s["security_versions"],**s.get("provider_versions",{})}.items())'
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_backend.py" .venv/bin/hermes /usr/lib/haos/runtime-provenance/backend-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ui_access.py" .venv/bin/python /usr/lib/haos /usr/lib/haos/hermes /usr/lib/haos/runtime-provenance/ui-access-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_gateway.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/gateway-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_native_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/native-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_bedrock_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/bedrock-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_account_providers.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/account-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_qwen_device.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/qwen-device-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_model_catalog.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/model-catalog-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_cloud_tokens.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/cloud-token-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_cloud_inference.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/cloud-model-http-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_native_account_flows.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/native-accounts-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_openrouter_login.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/openrouter-login-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider_profiles.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-wire-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_messages_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-messages-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_http_provider_matrix.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-http-matrix-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_aws_native.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-aws-native-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_converse_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-converse-replay-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_acp_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/acp-provider-build-probe.json /usr/lib/haos/copilot/copilot
rpm -q python3.11 python3.11-libs > /usr/lib/haos/python-runtime.txt
