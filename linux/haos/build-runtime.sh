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
uv sync --frozen --python /usr/bin/python3.11 --no-python-downloads --no-dev --extra web --extra messaging --extra anthropic --extra bedrock --extra vertex --extra azure-identity --extra matrix --extra voice --extra feishu
uv pip install --python .venv/bin/python --require-hashes --no-deps -r "$HAOS_RUNTIME_OVERLAY/requirements.txt"
uv pip check --python .venv/bin/python
# Fail the build on upstream registry drift. The setup process reads only this
# reviewed data snapshot; it must never import arbitrary plugins as root.
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/export_registry.py" /usr/lib/haos/hermes /tmp/haos-registry.json
cmp /tmp/haos-registry.json /usr/lib/haos/haos/hermes_registry.json
mkdir -p /usr/lib/haos/runtime-provenance
cp "$HAOS_RUNTIME_OVERLAY/source.json" "$HAOS_RUNTIME_OVERLAY/requirements.txt" "$HAOS_RUNTIME_OVERLAY/homeassistant-protocol-source.json" "$HAOS_RUNTIME_OVERLAY/irc-protocol-source.json" /usr/lib/haos/runtime-provenance/
uv pip freeze --python .venv/bin/python > /usr/lib/haos/runtime-provenance/installed.txt
# Installed /usr is immutable and runtime bytecode writes are disabled. Compile
# actual trusted sources here instead of parsing the entire cold import graph
# under QEMU TCG at first boot. Keep the canonical CLI and health deadline intact.
.venv/bin/python -I "$HAOS_RUNTIME_OVERLAY/compile_runtime.py"
test -x .venv/bin/hermes
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
.venv/bin/python -I -c 'import importlib.metadata,json;from pathlib import Path;s=json.loads(Path("/usr/lib/haos/runtime-provenance/source.json").read_text());assert all(importlib.metadata.version(n)==v for n,v in {**s["security_versions"],**s.get("provider_versions",{})}.items())'
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_backend.py" .venv/bin/hermes /usr/lib/haos/runtime-provenance/backend-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_media_backend.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/media-native-backend-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_media_backend.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/sms-media-native-backend-build-probe.json --sms
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_media_backend.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/email-media-native-backend-build-probe.json --email
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_artifact_backend.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/artifact-native-backend-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ui_access.py" .venv/bin/python /usr/lib/haos /usr/lib/haos/hermes /usr/lib/haos/runtime-provenance/ui-access-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_gateway.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/gateway-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_gateway_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/gateway-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_discord_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/discord-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_discord_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/discord-native-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_discord_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/discord-native-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_discord_history.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/discord-native-history-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_slack_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/slack-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_slack_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/slack-native-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_slack_history.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/slack-native-history-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_mattermost_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/mattermost-native-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_mattermost_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/mattermost-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_mattermost_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/mattermost-native-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_mattermost_history.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/mattermost-native-history-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_crypto.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-crypto-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_identity.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-identity-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_sync.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-sync-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_http.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-http-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_history.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-history-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_recipients.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-recipients-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_profile.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-profile-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_homeassistant_profile.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/homeassistant-prepared-profile-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_homeassistant_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/homeassistant-prepared-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_homeassistant_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/homeassistant-prepared-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_homeassistant_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/homeassistant-prepared-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_irc_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/irc-prepared-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-prepared-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_listener.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-prepared-listener-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-prepared-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_profile.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-prepared-profile-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_output.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/line-output-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_media.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-media-build-probe.json
HAOS_SPEECH_FIXTURE="$(mktemp -d /tmp/haos-speech-fixture.XXXXXX)"
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/fetch_speech_fixture.py" /tmp/herald-os/linux/haos "$HAOS_SPEECH_FIXTURE"
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_speech_backend.py" /tmp/herald-os/linux/haos "$HAOS_SPEECH_FIXTURE" /usr/lib/haos/runtime-provenance/speech-native-build-probe.json
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_voice.py" /tmp/herald-os/linux/haos "$HAOS_SPEECH_FIXTURE" /usr/lib/haos/runtime-provenance/line-voice-build-probe.json
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_sms_voice.py" /tmp/herald-os/linux/haos "$HAOS_SPEECH_FIXTURE" /usr/lib/haos/runtime-provenance/sms-voice-build-probe.json
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_voice.py" /tmp/herald-os/linux/haos "$HAOS_SPEECH_FIXTURE" /usr/lib/haos/runtime-provenance/email-voice-build-probe.json
rm -rf -- "$HAOS_SPEECH_FIXTURE"

.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_line_tls.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/line-prepared-tls-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_sms.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/sms-prepared-native-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_feishu_capture.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/feishu-original-capture-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_feishu_http.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/feishu-private-http-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_feishu_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/feishu-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_feishu_admission.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/feishu-native-admission-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_feishu_sdk.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/feishu-native-sdk-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_codec.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-codec-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_admission.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-admission-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_media.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-media-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_smtp.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/email-smtp-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_email_output.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/email-output-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_sms_output.py" /tmp/herald-os/linux/haos .venv/bin/hermes /usr/lib/haos/runtime-provenance/sms-output-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_irc_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/irc-prepared-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_irc_profile.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/irc-prepared-profile-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_irc_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/irc-prepared-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ntfy_profile.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/ntfy-native-profile-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ntfy_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/ntfy-native-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ntfy_transport.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/ntfy-native-transport-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_ntfy_ingress.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/ntfy-native-ingress-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_matrix_account.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/matrix-native-account-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_telegram_polling.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/telegram-polling-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_telegram_polling.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/telegram-held-build-probe.json held
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_telegram_delivery.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/telegram-delivery-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider_fallback_matrix.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-fallback-builder-matrix.json
for scenario in reasoning developer responses messages reasoning-stream developer-stream responses-stream messages-stream vertex vertex-stream reserved-tools reserved-tools-stream reserved-tools-reverse reserved-tools-reverse-stream context-aliases context-aliases-stream; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider_fallback_wire.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/provider-fallback-$scenario.json" "$scenario"
done
for mode in chat responses messages chat-legacy responses-legacy messages-legacy; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_agent_no_replay.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/main-agent-$mode-no-replay.json" "$mode"
done
for mode in chat chat-stream chat-moa chat-moa-stream responses messages responses-aliases messages-aliases chat-same-model responses-same-model messages-same-model opencode-chat opencode-chat-stream opencode-responses opencode-messages opencode-chat-moa opencode-chat-moa-stream; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_agent_fallback_replay.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/main-agent-$mode-fallback-replay.json" "$mode"
done
for mode in sdk-json moa-json moa-stream native-sdk-json native-moa-json native-moa-stream sdk-json-same-model moa-json-same-model moa-stream-same-model native-sdk-json-same-model native-moa-json-same-model native-moa-stream-same-model; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_chat_tool_replay.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/chat-tools-$mode.json" "$mode"
done
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_agent_replay_generation.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/agent-replay-generation-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider_route_names.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-route-names-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_router_reasoning.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/router-reasoning-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_native_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/native-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_bedrock_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/bedrock-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-provider-build-probe.json
for scenario in mixed stream mixed-stream mixed-messages-stream mixed-stream-abort mixed-messages-stream-abort reference-disconnect; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_provider.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/moa-$scenario-build-probe.json" "$scenario"
done
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_stream_scope.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-stream-scope-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_fallback_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-fallback-replay-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_fallback_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-fallback-json-replay-build-probe.json json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_stream_scope.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-chat-scope-build-probe.json chat
for task in moa_reference moa_aggregator; do
    .venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_no_replay.py" /tmp/herald-os/linux/haos "/usr/lib/haos/runtime-provenance/$task-no-replay.json" "$task"
done
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_moa_stream_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/moa-stream-replay-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_account_providers.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/account-provider-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_qwen_device.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/qwen-device-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_vertex_catalog.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/vertex-catalog-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_model_catalog.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/model-catalog-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_cloud_tokens.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/cloud-token-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_cloud_inference.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/cloud-model-http-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_native_account_flows.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/native-accounts-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_openrouter_login.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/openrouter-login-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_codex_account.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/codex-account-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_copilot_device.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/copilot-device-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_anthropic_account.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/anthropic-account-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_provider_profiles.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-wire-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_messages_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-messages-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_http_provider_matrix.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-http-matrix-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_aws_native.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-aws-native-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_aws_native.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-aws-profile-build-probe.json profile
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_aws_native.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-aws-default-chain-build-probe.json default-chain
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_aws_identity.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-aws-identity-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_converse_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-converse-replay-build-probe.json
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_converse_replay.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/provider-converse-route-scope-build-probe.json route-scope
.venv/bin/python "$HAOS_RUNTIME_OVERLAY/probe_acp_provider.py" /tmp/herald-os/linux/haos /usr/lib/haos/runtime-provenance/acp-provider-build-probe.json /usr/lib/haos/copilot/copilot
rpm -q python3.11 python3.11-libs > /usr/lib/haos/python-runtime.txt
