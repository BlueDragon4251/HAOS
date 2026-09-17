#!/usr/bin/env bash
# One-shot developer bootstrap for Hermes OS on macOS.
#   1. Fetch the pinned upstream snapshot (types for the gateway wire).
#   2. Install Node workspaces.
#   3. Link the system-bridge plugin into the user's Hermes plugins directory.
#   4. Verify a Hermes runtime with `serve` is reachable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# The /usr/bin shims refuse to run until the Xcode license is accepted; the CommandLineTools
# binaries behind them work. Prefer them so `npm install` (node-gyp) and git keep working.
if [[ -d /Library/Developer/CommandLineTools/usr/bin ]]; then
  export PATH="/Library/Developer/CommandLineTools/usr/bin:$PATH"
  export SDKROOT="${SDKROOT:-/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk}"
fi

echo "==> Syncing upstream snapshot"
bash "$ROOT/scripts/sync-upstream.sh"

echo "==> Installing Node workspaces"
(cd "$ROOT" && npm install)

# npm strips the executable bit from node-pty's prebuilt spawn-helper; the app also repairs this at
# runtime, but fixing it here keeps `npm run dist:mac` packaging a working binary.
helper="$ROOT/node_modules/node-pty/prebuilds/darwin-arm64/spawn-helper"
[[ -f "$helper" ]] && chmod 755 "$helper"

echo "==> Linking hermes-os-bridge plugin into $HERMES_HOME/plugins"
mkdir -p "$HERMES_HOME/plugins"
link="$HERMES_HOME/plugins/hermes-os-bridge"
if [[ -L "$link" || -e "$link" ]]; then
  rm -rf "$link"
fi
ln -s "$ROOT/plugins/hermes-os-bridge" "$link"

echo "==> Verifying Hermes runtime"
HERMES_CMD=()
if [[ -n "${HERMES_OS_HERMES_ROOT:-}" && -x "$HERMES_OS_HERMES_ROOT/venv/bin/python" ]]; then
  echo "    HERMES_OS_HERMES_ROOT=$HERMES_OS_HERMES_ROOT"
  HERMES_CMD=("$HERMES_OS_HERMES_ROOT/venv/bin/python" -m hermes_cli.main)
elif [[ -x "$HERMES_HOME/hermes-agent/venv/bin/python" ]]; then
  echo "    managed install: $HERMES_HOME/hermes-agent"
  HERMES_CMD=("$HERMES_HOME/hermes-agent/venv/bin/python" -m hermes_cli.main)
elif command -v hermes >/dev/null 2>&1; then
  echo "    hermes on PATH: $(command -v hermes)"
  HERMES_CMD=(hermes)
else
  echo "    WARNING: no Hermes runtime found. Install with:" >&2
  echo "      curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" >&2
fi

if [[ ${#HERMES_CMD[@]} -gt 0 ]]; then
  echo "==> Enabling the system bridge plugin and its toolset"
  # User plugins are opt-in (plugins.enabled) and a saved platform toolset list is authoritative, so
  # both must be recorded. The override prompt is answered "no" (stdin closed): the bridge never
  # replaces built-in tools.
  (cd "${HERMES_OS_HERMES_ROOT:-$HERMES_HOME/hermes-agent}" 2>/dev/null || true; "${HERMES_CMD[@]}" plugins enable hermes-os-bridge </dev/null >/dev/null 2>&1 || true)
  (cd "${HERMES_OS_HERMES_ROOT:-$HERMES_HOME/hermes-agent}" 2>/dev/null || true; "${HERMES_CMD[@]}" tools enable hermes_os </dev/null 2>&1 | tail -1 || true)
  # Upstream defers plugin tools behind its tool-search bridge; with the system tools hidden the
  # agent falls back to shell commands. Keep them direct (Settings -> Permissions can flip it back).
  echo "    tools.tool_search.enabled = off (system tools stay directly callable)"
  (cd "${HERMES_OS_HERMES_ROOT:-$HERMES_HOME/hermes-agent}" 2>/dev/null || true; "${HERMES_CMD[@]}" config set tools.tool_search.enabled off </dev/null >/dev/null 2>&1 || true)
fi

echo "==> Done. Start Hermes OS with: npm run dev"
