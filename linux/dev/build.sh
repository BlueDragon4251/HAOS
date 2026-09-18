#!/usr/bin/env bash
# Build the Hermes OS shell inside the Linux VM (run as the session user).
# Fetches the upstream snapshot, installs Node workspaces, links + enables the bridge plugin
# (scripts/bootstrap.sh), compiles the shell, and fixes Electron's sandbox helper permissions.
#
#   hermes-os-build            # after linux/dev/push.sh or hermes-os-sync
set -euo pipefail

REPO="${HERMES_OS_REPO:-$HOME/Hermes-OS}"
export PATH="$HOME/.local/bin:$PATH"

[[ -d "$REPO/apps/os" ]] || { echo "repo not found at $REPO (push it from the Mac: linux/dev/push.sh)" >&2; exit 1; }
cd "$REPO"

echo "==> bootstrap (upstream snapshot, npm install, bridge plugin)"
bash scripts/bootstrap.sh

# node-pty ships no Linux prebuilds; compile it once against the Electron ABI's Node.
if [[ ! -f node_modules/node-pty/build/Release/pty.node && ! -d "node_modules/node-pty/prebuilds/linux-$(uname -m | sed 's/aarch64/arm64/;s/x86_64/x64/')" ]]; then
  echo "==> compiling node-pty"
  (cd node_modules/node-pty && npx --yes node-gyp rebuild >/dev/null)
fi

echo "==> building shell"
npm run build --workspace apps/os

# Chromium's setuid sandbox helper must be root-owned 4755 when unprivileged user namespaces
# are unavailable; harmless otherwise.
SANDBOX="$REPO/node_modules/electron/dist/chrome-sandbox"
if [[ -f "$SANDBOX" && "$(stat -c '%u %a' "$SANDBOX")" != "0 4755" ]]; then
  sudo chown root:root "$SANDBOX" && sudo chmod 4755 "$SANDBOX" || true
fi

# Keep the installed session files in step with the repo (they are what greetd/cage run).
if [[ -d "$REPO/linux/session" ]] && command -v sudo >/dev/null; then
  sudo install -m 0755 "$REPO/linux/session/hermes-os-compositor" /usr/local/bin/hermes-os-compositor
  sudo install -m 0755 "$REPO/linux/session/hermes-os-session" /usr/local/bin/hermes-os-session
  sudo install -m 0644 "$REPO/linux/session/hermes-os.desktop" /usr/share/wayland-sessions/hermes-os.desktop
  for f in build.sh sync.sh restart-shell.sh shot.sh; do
    install -m 0755 "$REPO/linux/dev/$f" "$HOME/.local/bin/hermes-os-${f%.sh}"
  done
fi

echo "==> build complete: $REPO/apps/os/dist"
