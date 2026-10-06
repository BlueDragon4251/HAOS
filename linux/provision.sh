#!/usr/bin/env bash
# Turn a stock Fedora Cloud install into Herald OS Linux (Stage 1). Runs as root, idempotent.
# Invoked by cloud-init on first boot (see linux/vm/make-seed.sh); safe to re-run by hand:
#
#   sudo bash /usr/local/share/herald-os-linux/provision.sh
#
# What it does:
#   1. Installs the compositors (niri, cage), greeter (greetd), audio, networking, Electron runtime libs,
#      Node.js, and the CLI tools the Linux HostAdapter uses.
#   2. Installs Hermes Agent for the `hermes` user at the pinned upstream revision.
#   3. Installs the Herald OS session and makes greetd auto-login straight into it.
#   4. Builds the Herald OS shell if the repo is reachable (shared folder or pushed copy).
set -euo pipefail

PAYLOAD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_USER="${HERMES_USER:-hermes}"
HERMES_UID_HOME="$(getent passwd "$HERMES_USER" | cut -d: -f6)"
STATE_DIR=/var/lib/herald-os
LOG=/var/log/herald-os-provision.log

mkdir -p "$STATE_DIR"
exec > >(tee -a "$LOG") 2>&1
# cloud-init prints its own final message either way, so a failure has to say so here.
trap 'echo "==> Provisioning FAILED at line $LINENO. Full log: $LOG"' ERR
echo "==> Herald OS Linux provisioner $(date -Is) (payload $PAYLOAD)"

if [[ -f /etc/herald-os/ref ]]; then
  # shellcheck disable=SC1091
  source /etc/herald-os/ref
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
  niri cage greetd seatd polkit dbus-daemon xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-gnome xdg-user-dirs
  swaybg swaylock swayidle slurp wl-clipboard cliphist brightnessctl playerctl wtype
  pipewire pipewire-pulse wireplumber alsa-utils
  # Cloud images ship kernel-core only; the sound drivers (snd-hda-intel for the VM's audio) live here.
  kernel-modules
  NetworkManager NetworkManager-wifi bluez upower
  # Electron runtime libraries and fonts.
  nss atk at-spi2-atk cups-libs gtk3 libdrm mesa-libgbm mesa-dri-drivers alsa-lib libxkbcommon
  libXcomposite libXdamage libXrandr libXScrnSaver libxshmfence pango cairo
  google-noto-sans-fonts google-noto-emoji-color-fonts dejavu-sans-fonts liberation-fonts
  # Toolchain for the shell (node-pty is compiled locally).
  nodejs npm gcc-c++ make python3 git rsync tar
  # Tools the Linux HostAdapter / HostPlatform shell out to.
  xdg-utils glib2 plocate fd-find librsvg2-tools libnotify iproute procps-ng util-linux
  grim python3-pyyaml socat
  # Phase 2 services: OCR, Flatpak software, boot splash.
  tesseract tesseract-langpack-eng flatpak plymouth plymouth-scripts plymouth-plugin-script
  # The menu bar's quick panels and switches: power modes, pactl for the sound panel, night light.
  power-profiles-daemon pulseaudio-utils wlsunset
  # The capture suite: screen recording, QR codes, re-encoding (the colour picker uses slurp and grim).
  wf-recorder zbar ffmpeg-free
  # Rescue terminal shown by herald-os-session when the shell is not built.
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
# The VM's first-boot seed disc (linux/vm/make-seed.sh) stays attached for cloud-init; keep it out
# of Files and the desktop.
echo 'SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="cidata", ENV{UDISKS_IGNORE}="1"' >/etc/udev/rules.d/90-herald-os-hide-seed.rules
udevadm control --reload || true
udevadm trigger --subsystem-match=block || true

# ---------------------------------------------------------------------------------------------
step "Herald OS session"
install -m 0755 "$PAYLOAD/session/herald-os-compositor" /usr/local/bin/herald-os-compositor
install -m 0755 "$PAYLOAD/session/herald-os-session" /usr/local/bin/herald-os-session
install -m 0755 "$PAYLOAD/session/herald-os-niri-nested" /usr/local/bin/herald-os-niri-nested
install -m 0755 "$PAYLOAD/bin/herald-os" "$PAYLOAD/bin/herald-os-theme" "$PAYLOAD/bin/herald-os-omakase" "$PAYLOAD/bin/herald-os-update" "$PAYLOAD/bin/herald-os-idle" "$PAYLOAD/bin/herald-os-catalog" /usr/local/bin/
# foot's client and server entries are for scripts; Applications keeps Foot next to Herald's Terminal.
install -d /usr/local/share/applications
for entry in footclient foot-server; do
  if [[ -f "/usr/share/applications/$entry.desktop" ]]; then
    printf '[Desktop Entry]\nType=Application\nName=%s\nHidden=true\n' "$entry" >"/usr/local/share/applications/$entry.desktop"
  fi
done
# Themes and omakase lists for machines without the repo checked out. The cloud-init payload is
# unpacked in this very folder, and cp refuses to copy a folder onto itself.
SHARE=/usr/local/share/herald-os-linux
install -d "$SHARE/themes" "$SHARE/omakase" "$SHARE/niri" "$SHARE/catalog"
if [[ "$(realpath "$PAYLOAD")" != "$(realpath "$SHARE")" ]]; then
  cp -R "$PAYLOAD"/themes/. "$SHARE/themes/"
  cp -R "$PAYLOAD"/omakase/. "$SHARE/omakase/"
  cp -R "$PAYLOAD"/catalog/. "$SHARE/catalog/"
  cp "$PAYLOAD/niri/config.kdl" "$SHARE/niri/config.kdl"
fi
# Daily update check (user timer) and the default theme.
sudo -u "$HERMES_USER" -H mkdir -p "$HERMES_UID_HOME/.config/systemd/user"
install -m 0644 -o "$HERMES_USER" -g "$HERMES_USER" "$PAYLOAD/session/herald-os-update-check.service" "$PAYLOAD/session/herald-os-update-check.timer" "$HERMES_UID_HOME/.config/systemd/user/"
sudo -u "$HERMES_USER" -H env XDG_RUNTIME_DIR="/run/user/$(id -u "$HERMES_USER")" systemctl --user enable herald-os-update-check.timer 2>/dev/null || true
sudo -u "$HERMES_USER" -H herald-os-theme set "$(sudo -u "$HERMES_USER" -H herald-os-theme current)" || true
# niri config for the session user, rendered with their keymap (managed; local.kdl is the user's).
sudo -u "$HERMES_USER" -H mkdir -p "$HERMES_UID_HOME/.config/niri" "$HERMES_UID_HOME/.config/swaylock"
sudo -u "$HERMES_USER" -H herald-os keymap apply || install -m 0644 -o "$HERMES_USER" -g "$HERMES_USER" "$PAYLOAD/niri/config.kdl" "$HERMES_UID_HOME/.config/niri/config.kdl"
install -m 0644 -o "$HERMES_USER" -g "$HERMES_USER" "$PAYLOAD/session/swaylock.conf" "$HERMES_UID_HOME/.config/swaylock/config"

# ---------------------------------------------------------------------------------------------
step "Boot splash (Plymouth) and Flathub"
if command -v plymouth-set-default-theme >/dev/null; then
  install -d /usr/share/plymouth/themes/herald-os
  install -m 0644 "$PAYLOAD"/plymouth/herald-os/* /usr/share/plymouth/themes/herald-os/
  if [[ "$(plymouth-set-default-theme 2>/dev/null)" != "herald-os" ]]; then
    plymouth-set-default-theme herald-os || echo "WARNING: could not set the Plymouth theme"
    # The splash has to be in every kernel's initramfs, not only the running one's (what -R rebuilds):
    # the package step usually installs a newer kernel, and that is the one the next boot starts.
    dracut -f --regenerate-all || echo "WARNING: could not rebuild the initramfs"
    # Show the splash instead of the console on boot. With a serial console on the kernel command
    # line (the VM's), Plymouth falls back to scrolling text unless told to ignore it.
    if command -v grubby >/dev/null; then
      grubby --update-kernel=ALL --args="rhgb quiet plymouth.ignore-serial-consoles" || true
    fi
  fi
fi
if command -v flatpak >/dev/null; then
  flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo || true
fi
install -d /usr/share/wayland-sessions
install -m 0644 "$PAYLOAD/session/herald-os.desktop" /usr/share/wayland-sessions/herald-os.desktop
install -d /etc/greetd
install -m 0644 "$PAYLOAD/session/greetd-config.toml" /etc/greetd/config.toml
sed -i "s/^user = .*/user = \"$HERMES_USER\"/" /etc/greetd/config.toml
systemctl set-default graphical.target
systemctl enable greetd

# Developer helpers for the hermes user. (`install -d` would create ~/.local as root; keep every
# directory under the home owned by the session user or uv/npm fail later.)
sudo -u "$HERMES_USER" -H mkdir -p "$HERMES_UID_HOME/.local/bin" "$HERMES_UID_HOME/.local/share" "$HERMES_UID_HOME/.local/state" "$HERMES_UID_HOME/.config/herald-os"
chown -R "$HERMES_USER:$HERMES_USER" "$HERMES_UID_HOME/.local" "$HERMES_UID_HOME/.config"
for f in build.sh sync.sh restart-shell.sh shot.sh; do
  install -m 0755 -o "$HERMES_USER" -g "$HERMES_USER" "$PAYLOAD/dev/$f" "$HERMES_UID_HOME/.local/bin/herald-os-${f%.sh}"
done

# ---------------------------------------------------------------------------------------------
step "Hermes Agent ($HERMES_REF) for $HERMES_USER"
HERMES_HOME="$HERMES_UID_HOME/.hermes"
AGENT="$HERMES_HOME/hermes-agent"
if [[ ! -x "$AGENT/venv/bin/python" ]]; then
  sudo -u "$HERMES_USER" -H bash -euo pipefail -c "
    mkdir -p '$HERMES_HOME'
    if [[ ! -d '$AGENT/.git' ]]; then
      # Every commit, but file contents only as checkouts need them: a quarter of the full download.
      git clone --filter=blob:none https://github.com/NousResearch/hermes-agent '$AGENT'
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

# Voice: local transcription, free neural voices and the "hey hermes" wake word.
sudo -u "$HERMES_USER" -H bash -euo pipefail -c "
  cd '$AGENT'
  PATH=\"\$HOME/.local/bin:\$PATH\" uv pip install --python venv/bin/python -q -e '.[voice,edge-tts,wake-openwakeword]' || echo 'voice extras failed; voice falls back to cloud providers'
"

# ---------------------------------------------------------------------------------------------
step "Herald OS shell"
REPO="$HERMES_UID_HOME/Herald-OS"
if mountpoint -q /mnt/herald-os 2>/dev/null; then
  echo "shared folder mounted at /mnt/herald-os; syncing and building"
  sudo -u "$HERMES_USER" -H bash "$PAYLOAD/dev/sync.sh" || echo "WARNING: shell build failed; see above"
elif [[ -d "$REPO/apps/desktop" ]]; then
  echo "repo present at $REPO; building"
  sudo -u "$HERMES_USER" -H bash "$PAYLOAD/dev/build.sh" || echo "WARNING: shell build failed; see above"
else
  echo "repo not present yet. From the Mac run: bash linux/dev/push.sh"
fi

# ---------------------------------------------------------------------------------------------
step "Omakase software set (HERALD_OS_OMAKASE=0 to skip)"
if [[ "${HERALD_OS_OMAKASE:-1}" == "1" ]]; then
  herald-os-omakase install --packages || echo "WARNING: omakase packages incomplete"
  sudo -u "$HERMES_USER" -H herald-os-omakase install --flatpaks || echo "WARNING: omakase flatpaks incomplete"
  # Web apps need the shell's icon fetch; they are installed on first login by herald-os-session.
fi

date -Is >"$STATE_DIR/provisioned"
echo "==> Provisioning complete. greetd will start Herald OS on the next boot (or: systemctl start greetd)."
