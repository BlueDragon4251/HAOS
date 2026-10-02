#!/usr/bin/env bash
# Build the Herald OS shell inside the Linux VM (run as the session user).
# Fetches the upstream snapshot, installs Node workspaces, links + enables the bridge plugin
# (scripts/bootstrap.sh), compiles the shell, and fixes Electron's sandbox helper permissions.
#
#   herald-os-build            # after linux/dev/push.sh or herald-os-sync
set -euo pipefail

REPO="${HERALD_OS_REPO:-$HOME/Herald-OS}"
export PATH="$HOME/.local/bin:$PATH"

[[ -d "$REPO/apps/desktop" ]] || { echo "repo not found at $REPO (push it from the Mac: linux/dev/push.sh)" >&2; exit 1; }
cd "$REPO"

echo "==> bootstrap (upstream snapshot, npm install, bridge plugin)"
bash scripts/bootstrap.sh

# node-pty ships no Linux prebuilds; compile it once against the Electron ABI's Node.
if [[ ! -f node_modules/node-pty/build/Release/pty.node && ! -d "node_modules/node-pty/prebuilds/linux-$(uname -m | sed 's/aarch64/arm64/;s/x86_64/x64/')" ]]; then
  echo "==> compiling node-pty"
  (cd node_modules/node-pty && npx --yes node-gyp rebuild >/dev/null)
fi

echo "==> building shell"
npm run build --workspace apps/desktop

# Electron downloads its binary on first use, not at npm install: fetch it now so the first login
# does not wait on a download and the sandbox helper below exists.
(cd "$REPO/apps/desktop" && node -e "require('electron')")
# Chromium's setuid sandbox helper must be root-owned 4755 when unprivileged user namespaces
# are unavailable; harmless otherwise.
SANDBOX="$(dirname "$(cd "$REPO/apps/desktop" && node -p "require('electron')")")/chrome-sandbox"
if [[ -f "$SANDBOX" && "$(stat -c '%u %a' "$SANDBOX")" != "0 4755" ]]; then
  sudo chown root:root "$SANDBOX" && sudo chmod 4755 "$SANDBOX" || true
fi

# Keep the installed session files in step with the repo (they are what greetd/cage run).
if [[ -d "$REPO/linux/session" ]] && command -v sudo >/dev/null; then
  sudo install -m 0755 "$REPO/linux/session/herald-os-compositor" /usr/local/bin/herald-os-compositor
  sudo install -m 0755 "$REPO/linux/session/herald-os-session" /usr/local/bin/herald-os-session
  sudo install -m 0755 "$REPO/linux/session/herald-os-niri-nested" /usr/local/bin/herald-os-niri-nested
  sudo install -m 0644 "$REPO/linux/session/herald-os.desktop" /usr/share/wayland-sessions/herald-os.desktop
  sudo install -m 0755 "$REPO/linux/bin/herald-os" "$REPO/linux/bin/herald-os-theme" "$REPO/linux/bin/herald-os-omakase" "$REPO/linux/bin/herald-os-update" /usr/local/bin/
  mkdir -p "$HOME/.config/systemd/user"
  install -m 0644 "$REPO/linux/session/herald-os-update-check.service" "$REPO/linux/session/herald-os-update-check.timer" "$HOME/.config/systemd/user/"
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable herald-os-update-check.timer 2>/dev/null || true
  mkdir -p "$HOME/.config/niri" "$HOME/.config/swaylock"
  install -m 0644 "$REPO/linux/niri/config.kdl" "$HOME/.config/niri/config.kdl"
  install -m 0644 "$REPO/linux/session/swaylock.conf" "$HOME/.config/swaylock/config"
  if [[ -d /usr/share/plymouth/themes ]]; then
    sudo install -d /usr/share/plymouth/themes/herald-os
    sudo install -m 0644 "$REPO"/linux/plymouth/herald-os/* /usr/share/plymouth/themes/herald-os/
  fi
  for f in build.sh sync.sh restart-shell.sh shot.sh; do
    install -m 0755 "$REPO/linux/dev/$f" "$HOME/.local/bin/herald-os-${f%.sh}"
  done
  sudo install -d /usr/local/share/herald-os-linux/themes /usr/local/share/herald-os-linux/omakase
  sudo cp -R "$REPO"/linux/themes/. /usr/local/share/herald-os-linux/themes/
  sudo cp -R "$REPO"/linux/omakase/. /usr/local/share/herald-os-linux/omakase/

  echo "==> one-shot migrations"
  HERALD_OS_REPO="$REPO" bash "$REPO/linux/bin/herald-os-update" --migrate || echo "WARNING: a migration failed; see above"
fi

echo "==> build complete: $REPO/apps/desktop/dist"
