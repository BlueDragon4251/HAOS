#!/usr/bin/env bash
# Live kiosk: start a real X11 graphical welcome screen; fail over to TTY installer.
set -Eeuo pipefail
export HOME=/root
export XDG_RUNTIME_DIR=/run/haos-kiosk
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"
if command -v xinit >/dev/null && command -v Xorg >/dev/null && command -v python3 >/dev/null; then
  /usr/bin/xinit /usr/bin/python3 /usr/local/sbin/haos-gui.py -- /usr/bin/Xorg :0 -nolisten tcp vt1 && exit 0
fi
printf '\nGraphical UI unavailable. Switching to accessible text installer.\n'
exec /usr/bin/bash /usr/local/sbin/haos-install.sh
