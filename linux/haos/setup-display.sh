#!/usr/bin/env bash
# Isolated root-only X display. No listening TCP socket, no user X clients.
set -euo pipefail
[[ "$(id -u)" == 0 ]] || exit 1
[[ -f /etc/haos/enabled ]] || exit 1
[[ -z "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" ]] || exit 1
umask 077
AUTH=/run/haos-setup-display/Xauthority
install -d -m 0700 /run/haos-setup-display
touch "$AUTH"
chmod 0600 "$AUTH"
COOKIE="$(/usr/bin/mcookie)"
[[ "$COOKIE" =~ ^[0-9a-f]{32}$ ]] || exit 1
/usr/bin/xauth -f "$AUTH" add :8 MIT-MAGIC-COOKIE-1 "$COOKIE"
unset COOKIE
export XAUTHORITY="$AUTH" HOME=/root HAOS_TRUSTED_SETUP=1
# Xorg uses physical VT1 only while the setup gate blocks the normal observer.
# DISPLAY :8 is an isolated X server number; it is independent of the VT index.
# On completion xinit stops the private server; service stays disabled until
# this setup mode is QEMU and hardware tested.
exec /usr/bin/xinit /usr/lib/haos/setup-gui-session.sh -- /usr/bin/Xorg :8 vt1 -auth "$AUTH" -nolisten tcp -noreset
