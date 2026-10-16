#!/usr/bin/env python3
"""Inject first-boot scripts into a standalone Fedora Live kickstart."""
from pathlib import Path
import base64
import sys

root=Path(__file__).resolve().parents[2]
out=Path(sys.argv[1])
base="""# Standalone Fedora 44 live image installer composition (not target disk instructions)
lang en_US.UTF-8
keyboard --vckeymap=de --xlayouts=at
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
shim-x64
grub2-efi-x64
grub2-efi-x64-cdboot
livecd-tools
bash
NetworkManager
xorg-x11-server-Xorg
xorg-x11-xinit
xterm
python3-tkinter
xorg-x11-drv-libinput
xorg-x11-drv-evdev
openbox
xrandr
setxkbmap
kbd
libinput-utils
mesa-dri-drivers
dejavu-sans-mono-fonts
podman
skopeo
bootc
NetworkManager-wifi
NetworkManager-tui
iwlwifi-mvm-firmware
iwlwifi-mld-firmware
iwlbluetooth-firmware
alsa-sof-firmware
curl
util-linux
systemd-udev
parted
pciutils
nvme-cli
-gnome-shell
%end
"""
payload=""
for filename in ("haos-install.sh","private-install.sh","haos-gui.py","haos-start-gui.sh","haos-xsession.sh","haos-console.sh","haos-disk-safety.py","haos-storage-diagnostics.sh","haos-dev-wizard.py","haos_install_core.py"):
    data=(root/"scripts/netinstall"/filename).read_bytes()
    encoded=base64.b64encode(data).decode()
    payload+=f"echo '{encoded}' | base64 -d > /usr/local/sbin/{filename}\nchmod 755 /usr/local/sbin/{filename}\n"
post="""\n%post --log=/root/haos-live-post.log
set -eu
mkdir -p /etc/systemd/system /usr/local/sbin
""" + payload + """
cat > /etc/systemd/system/haos-installer.service <<'UNIT'
[Unit]
Description=HAOS Dual Channel Installer
After=systemd-logind.service NetworkManager.service
Conflicts=getty@tty1.service
[Service]
Type=simple
ExecStart=/usr/local/sbin/haos-start-gui.sh
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
cat > /etc/systemd/system/haos-installer-console.service <<'UNIT'
[Unit]
Description=HAOS physical keyboard text fallback on TTY2
After=systemd-logind.service
Conflicts=getty@tty2.service
[Service]
Type=simple
ExecStart=/usr/bin/bash /usr/local/sbin/haos-console.sh
StandardInput=tty-force
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty2
TTYReset=yes
TTYVHangup=yes
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
systemctl mask getty@tty2.service
systemctl enable haos-installer-console.service
%end
"""
# Fedora kickstart base usually already includes %post blocks;
# appended sections are independent supported Kickstart sections.
out.write_text(base+"\n"+packages+post)
