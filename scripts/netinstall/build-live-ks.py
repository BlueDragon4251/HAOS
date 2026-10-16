#!/usr/bin/env python3
"""Inject first-boot scripts into a standalone Fedora Live kickstart."""
from pathlib import Path
import base64
import sys

root=Path(__file__).resolve().parents[2]
out=Path(sys.argv[1])
base="""# Standalone Fedora 44 live image installer composition (not target disk instructions)
lang en_US.UTF-8
keyboard us
timezone UTC --utc
selinux --enforcing
firewall --enabled
services --enabled=NetworkManager,sshd
network --bootproto=dhcp --device=link --activate
rootpw --lock
bootloader --location=mbr
zerombr
clearpart --all --initlabel
part / --fstype=ext4 --size=4096
shutdown
repo --name=fedora --mirrorlist=https://mirrors.fedoraproject.org/metalink?repo=fedora-44&arch=x86_64
repo --name=updates --mirrorlist=https://mirrors.fedoraproject.org/metalink?repo=updates-released-f44&arch=x86_64
"""
# Package customization supplements, rather than replaces, Fedora's live core.
packages="""\n%packages
@core
kernel
kernel-modules
kernel-modules-extra
dracut-live
livecd-tools
bash
NetworkManager
podman
bootc
NetworkManager-wifi
iwlwifi-mvm-firmware
iwlwifi-mld-firmware
iwlbluetooth-firmware
alsa-sof-firmware
curl
util-linux
systemd-udev
parted
-gnome-shell
%end
"""
payload=""
for filename in ("haos-install.sh","private-install.sh"):
    data=(root/"scripts/netinstall"/filename).read_bytes()
    encoded=base64.b64encode(data).decode()
    payload+=f"echo '{encoded}' | base64 -d > /usr/local/sbin/{filename}\nchmod 700 /usr/local/sbin/{filename}\n"
post="""\n%post --log=/root/haos-live-post.log
set -eu
mkdir -p /etc/systemd/system /usr/local/sbin
""" + payload + """
cat > /etc/systemd/system/haos-installer.service <<'UNIT'
[Unit]
Description=HAOS Dual Channel Installer
After=network.target getty@tty1.service
Conflicts=getty@tty1.service
[Service]
Type=idle
ExecStart=/usr/bin/bash /usr/local/sbin/haos-install.sh
StandardInput=tty-force
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
Restart=no
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable NetworkManager.service
systemctl enable haos-installer.service
%end
"""
# Fedora kickstart base usually already includes %post blocks;
# appended sections are independent supported Kickstart sections.
out.write_text(base+"\n"+packages+post)
