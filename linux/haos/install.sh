#!/usr/bin/env bash
# Called only by the image builder. No disk operations or shared owner credentials.
set -euo pipefail
HAOS_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d /usr/lib/haos /usr/lib/systemd/system /usr/lib/sysusers.d /etc/haos
cp -R "$HAOS_SOURCE/haos" /usr/lib/haos/
install -m 0644 "$HAOS_SOURCE"/*.service /usr/lib/systemd/system/
install -m 0644 "$HAOS_SOURCE/haos.sysusers" /usr/lib/sysusers.d/haos.conf
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
install -d /etc/systemd/system/greetd.service.d
cat >/etc/systemd/system/greetd.service.d/haos-observer.conf <<'UNIT'
[Unit]
Requires=herald-os-firstboot.service haos-observer-security.service
After=herald-os-firstboot.service haos-observer-security.service
UNIT
systemctl enable haos-controller.service haos-hermes.service haos-policy.service haos-observer-security.service
