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
exec /usr/bin/haos-setup-desktop
