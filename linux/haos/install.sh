#!/usr/bin/env bash
# Called only by the image builder. No disk operations or shared owner credentials.
set -euo pipefail
HAOS_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d /usr/lib/haos /usr/lib/systemd/system /usr/lib/sysusers.d /etc/haos
cp -R "$HAOS_SOURCE/haos" /usr/lib/haos/
install -m 0644 "$HAOS_SOURCE"/*.service /usr/lib/systemd/system/
install -m 0644 "$HAOS_SOURCE"/*.socket /usr/lib/systemd/system/
install -m 0644 "$HAOS_SOURCE"/*.timer /usr/lib/systemd/system/
install -m 0644 "$HAOS_SOURCE/runtime/backup-schedule-entry.py" /usr/lib/haos/backup-schedule-entry.py
install -m 0644 "$HAOS_SOURCE/haos.sysusers" /usr/lib/sysusers.d/haos.conf
# Only the physical graphical observer can manage Wi-Fi; never grant to the
# separate Hermes agent, controllers, remote sessions or generic local users.
install -Dm0644 "$HAOS_SOURCE/networkmanager-observer.rules" /usr/share/polkit-1/rules.d/49-haos-observer-network.rules
systemd-sysusers /usr/lib/sysusers.d/haos.conf
python3 - <<'PY'
import pwd
from pathlib import Path
agent = pwd.getpwnam('haos-agent')
# Minimal NSS identity; never expose the host's account inventory or shadow file.
Path('/usr/lib/haos/passwd').write_text(f'haos-agent:x:{agent.pw_uid}:{agent.pw_gid}:HAOS agent:/home/agent:/usr/sbin/nologin\n')
Path('/usr/lib/haos/group').write_text(f'haos-agent:x:{agent.pw_gid}:\n')
PY
chmod 0644 /usr/lib/haos/passwd /usr/lib/haos/group
install -Dm0755 "$HAOS_SOURCE/../bin/haos-owner" /usr/bin/haos-owner
install -Dm0755 "$HAOS_SOURCE/../bin/haos-setup-desktop" /usr/bin/haos-setup-desktop
install -Dm0755 "$HAOS_SOURCE/setup-display.sh" /usr/lib/haos/setup-display.sh
install -Dm0755 "$HAOS_SOURCE/setup-gui-session.sh" /usr/lib/haos/setup-gui-session.sh
install -Dm0755 "$HAOS_SOURCE/../bin/haos-recovery" /usr/bin/haos-recovery
install -Dm0644 "$HAOS_SOURCE/../bin/haos-recovery" /usr/lib/haos/recovery-console.py
install -d /etc/systemd/system/greetd.service.d
cat >/etc/systemd/system/greetd.service.d/haos-observer.conf <<'UNIT'
[Unit]
Requires=herald-os-firstboot.service haos-observer-security.service haos-dashboard-policy.service
After=herald-os-firstboot.service haos-observer-security.service haos-dashboard-policy.service
UNIT
systemctl enable haos-update.timer
systemctl enable haos-controller.service haos-hermes.service haos-policy.service haos-network.service haos-observer-security.service haos-dashboard-policy.service haos-gateway.service haos-recovery.service haos-provider.socket haos-applications.socket
