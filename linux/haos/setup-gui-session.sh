#!/usr/bin/env bash
# Fixed local firstboot keyboard before typing the administrator password.
set -euo pipefail
[[ "$(id -u)" == 0 ]] || exit 1
[[ "${DISPLAY:-}" == ":8" && "${HAOS_TRUSTED_SETUP:-}" == "1" ]] || exit 1
[[ -r /run/haos-setup-display/Xauthority ]] || exit 1
# Avoid the default QWERTY keyboard in trusted setup. Can be changed in wizard.
/usr/bin/setxkbmap -layout at || {
  echo "HAOS: cannot activate trusted initial Austrian keymap; stopping before password entry" >&2
  exit 1
}
# Switch the physical console to the isolated graphical administrator seat
# after X is ready. Never expose a root Wayland/Electron session.
(/usr/bin/chvt 1 || echo "HAOS setup: VT1 activation requires physical console selection" >&2)
exec /usr/bin/haos-setup-desktop
