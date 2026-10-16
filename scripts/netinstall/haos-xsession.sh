#!/usr/bin/env bash
# X11 startup process: keyboard/mouse focus and correct screen size are critical.
set -Eeuo pipefail
export XDG_CURRENT_DESKTOP=HAOS
export GDK_BACKEND=x11
mkdir -p /run/haos-kiosk
{
  printf '=== X display modes ===\n'
  xrandr --query || true
  printf '\n=== Kernel input devices ===\n'
  cat /proc/bus/input/devices || true
  printf '\n=== evdev nodes ===\n'
  ls -l /dev/input/ /dev/input/by-path/ || true
  printf '\n=== libinput devices ===\n'
  if command -v libinput >/dev/null; then libinput list-devices || true; fi
} > /run/haos-kiosk/hardware.log 2>&1
if command -v xrandr >/dev/null; then xrandr --auto || true; fi
if command -v openbox >/dev/null; then
  openbox --sm-disable >/run/haos-kiosk/openbox.log 2>&1 &
  WM_PID=$!
  trap 'kill "$WM_PID" 2>/dev/null || true' EXIT
  sleep 1
fi
exec /usr/bin/python3 /usr/local/sbin/haos-gui.py
