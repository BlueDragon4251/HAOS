#!/usr/bin/env bash
# Start the HAOS live kiosk with a real window manager and X11 diagnostics.
set -Eeuo pipefail
export HOME=/root
export XDG_RUNTIME_DIR=/run/haos-kiosk
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"
if command -v xinit >/dev/null && command -v Xorg >/dev/null && command -v python3 >/dev/null; then
  if /usr/bin/xinit /usr/bin/bash /usr/local/sbin/haos-xsession.sh -- /usr/bin/Xorg :0 -nolisten tcp vt1; then
    exit 0
  fi
fi
printf '\nHAOS graphical interface could not start. Text installer remains on Ctrl+Alt+F2.\n'
exec /usr/bin/bash /usr/local/sbin/haos-install.sh
