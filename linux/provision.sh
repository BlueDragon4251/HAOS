#!/usr/bin/env bash
# Turn a stock Fedora Cloud install into Hermes OS Linux (Stage 1). Runs as root, idempotent.
# Invoked by cloud-init on first boot (see linux/vm/make-seed.sh); safe to re-run by hand:
#
#   sudo bash /usr/local/share/hermes-os-linux/provision.sh
#
# What it does:
#   1. Installs the compositor (cage), greeter (greetd), audio, networking, Electron runtime libs,
#      Node.js, and the CLI tools the Linux HostAdapter uses.
#   2. Installs Hermes Agent for the `hermes` user at the pinned upstream revision.
#   3. Installs the Hermes OS session and makes greetd auto-login straight into it.
#   4. Builds the Hermes OS shell if the repo is reachable (shared folder or pushed copy).
set -euo pipefail

PAYLOAD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_USER="${HERMES_USER:-hermes}"
HERMES_UID_HOME="$(getent passwd "$HERMES_USER" | cut -d: -f6)"
STATE_DIR=/var/lib/hermes-os
LOG=/var/log/hermes-os-provision.log

mkdir -p "$STATE_DIR"
exec > >(tee -a "$LOG") 2>&1
echo "==> Hermes OS Linux provisioner $(date -Is) (payload $PAYLOAD)"

if [[ -f /etc/hermes-os/ref ]]; then
  # shellcheck disable=SC1091
  source /etc/hermes-os/ref
fi
HERMES_REF="${HERMES_REF:-main}"

step() { echo; echo "--- $*"; }

# ---------------------------------------------------------------------------------------------
step "SELinux permissive for Stage 1 (greetd + cage lack a tailored policy; Stage 2 writes one)"
if command -v setenforce >/dev/null; then
  setenforce 0 || true
  sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config || true
fi

# ---------------------------------------------------------------------------------------------
step "Packages"
PACKAGES=(
  # Session.
  cage greetd seatd polkit dbus-daemon xdg-desktop-portal xdg-desktop-portal-gtk xdg-user-dirs
  pipewire pipewire-pulse wireplumber
  NetworkManager NetworkManager-wifi bluez upower
  # Electron runtime libraries and fonts.
  nss atk at-spi2-atk cups-libs gtk3 libdrm mesa-libgbm mesa-dri-drivers alsa-lib libxkbcommon
  libXcomposite libXdamage libXrandr libXScrnSaver libxshmfence pango cairo
  google-noto-sans-fonts google-noto-emoji-color-fonts dejavu-sans-fonts liberation-fonts
  # Toolchain for the shell (node-pty is compiled locally).
  nodejs npm gcc-c++ make python3 git rsync tar
  # Tools the Linux HostAdapter / HostPlatform shell out to.
  xdg-utils glib2 plocate fd-find librsvg2-tools libnotify iproute procps-ng util-linux
  grim wl-clipboard
  # Rescue terminal shown by hermes-os-session when the shell is not built.
  foot
  # A browser, a file manager and an editor so the Dock and `system_open` have real targets.
  firefox nautilus gnome-text-editor
)
dnf -y install --setopt=install_weak_deps=False "${PACKAGES[@]}"

# `seat`/`render` groups exist now; make sure the session user is in the device groups.
usermod -aG video,input,render,audio,seat "$HERMES_USER" || true

# ---------------------------------------------------------------------------------------------
step "Services"
systemctl enable --now NetworkManager || true
systemctl enable --now seatd || true
systemctl enable --now bluetooth || true
systemctl enable --now plocate-updatedb.timer || true
systemctl enable sshd || true
# Let the hermes user's systemd instance (pipewire, portals) survive when no one is logged in.
loginctl enable-linger "$HERMES_USER" || true

# ---------------------------------------------------------------------------------------------
step "Hermes OS session"
install -m 0755 "$PAYLOAD/session/hermes-os-compositor" /usr/local/bin/hermes-os-compositor
install -m 0755 "$PAYLOAD/session/hermes-os-session" /usr/local/bin/hermes-os-session
install -d /usr/share/wayland-sessions
install -m 0644 "$PAYLOAD/session/hermes-os.desktop" /usr/share/wayland-sessions/hermes-os.desktop
install -d /etc/greetd
install -m 0644 "$PAYLOAD/session/greetd-config.toml" /etc/greetd/config.toml
sed -i "s/^user = .*/user = \"$HERMES_USER\"/" /etc/greetd/config.toml
systemctl set-default graphical.target
systemctl enable greetd

# Developer helpers for the hermes user.
install -d -o "$HERMES_USER" -g "$HERMES_USER" "$HERMES_UID_HOME/.local/bin"
for f in build.sh sync.sh restart-shell.sh shot.sh; do
  install -m 0755 -o "$HERMES_USER" -g "$HERMES_USER" "$PAYLOAD/dev/$f" "$HERMES_UID_HOME/.local/bin/hermes-os-${f%.sh}"
done

# ---------------------------------------------------------------------------------------------
step "Hermes Agent ($HERMES_REF) for $HERMES_USER"
HERMES_HOME="$HERMES_UID_HOME/.hermes"
AGENT="$HERMES_HOME/hermes-agent"
if [[ ! -x "$AGENT/venv/bin/python" ]]; then
  sudo -u "$HERMES_USER" -H bash -euo pipefail -c "
    mkdir -p '$HERMES_HOME'
    if [[ ! -d '$AGENT/.git' ]]; then
      git clone https://github.com/NousResearch/hermes-agent '$AGENT'
    fi
    cd '$AGENT'
    git fetch --quiet origin '$HERMES_REF' || true
    git checkout --quiet '$HERMES_REF' || git checkout --quiet main
    # setup-hermes.sh asks two yes/no questions (ripgrep, setup wizard); answer no to both.
    printf 'n\nn\n' | bash ./setup-hermes.sh
  "
else
  echo "already installed: $AGENT"
fi

# ---------------------------------------------------------------------------------------------
step "Hermes OS shell"
REPO="$HERMES_UID_HOME/Hermes-OS"
if mountpoint -q /mnt/hermes-os 2>/dev/null; then
  echo "shared folder mounted at /mnt/hermes-os; syncing and building"
  sudo -u "$HERMES_USER" -H bash "$PAYLOAD/dev/sync.sh" || echo "WARNING: shell build failed; see above"
elif [[ -d "$REPO/apps/os" ]]; then
  echo "repo present at $REPO; building"
  sudo -u "$HERMES_USER" -H bash "$PAYLOAD/dev/build.sh" || echo "WARNING: shell build failed; see above"
else
  echo "repo not present yet. From the Mac run: bash linux/dev/push.sh"
fi

date -Is >"$STATE_DIR/provisioned"
echo "==> Provisioning complete. greetd will start Hermes OS on the next boot (or: systemctl start greetd)."
