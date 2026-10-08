#!/usr/bin/env bash
# Called only by the image builder. No disk operations or shared owner credentials.
set -euo pipefail
HAOS_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d /usr/lib/haos /usr/lib/systemd/system /usr/lib/sysusers.d /etc/haos
cp -R "$HAOS_SOURCE/haos" /usr/lib/haos/
install -m 0644 "$HAOS_SOURCE"/*.service /usr/lib/systemd/system/
install -m 0644 "$HAOS_SOURCE/haos.sysusers" /usr/lib/sysusers.d/haos.conf
systemd-sysusers /usr/lib/sysusers.d/haos.conf
install -Dm0755 "$HAOS_SOURCE/../bin/haos-owner" /usr/bin/haos-owner
systemctl enable haos-controller.service haos-hermes.service haos-policy.service
