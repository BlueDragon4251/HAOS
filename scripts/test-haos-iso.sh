#!/usr/bin/env bash
# Installs only into fresh QEMU disk files; never opens a host block device for writes.
set -euo pipefail
HAOS_TEST_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HAOS_TEST_ISO="$(realpath "${1:?usage: test-haos-iso.sh <development.iso> <evidence-directory>}")"
HAOS_TEST_EVIDENCE="$(realpath -m "${2:?an evidence directory is required}")"
HAOS_TEST_GUEST_PROBE="$(realpath "${3:-$HAOS_TEST_REPO/tests/e2e/haos_guest.py}")"
[[ -f "$HAOS_TEST_ISO" && ! -b "$HAOS_TEST_ISO" ]] || { echo "ISO must be a regular file" >&2; exit 1; }
[[ -f "$HAOS_TEST_GUEST_PROBE" && ! -b "$HAOS_TEST_GUEST_PROBE" ]] || { echo "Guest probe must be a regular file" >&2; exit 1; }
mkdir -p "$HAOS_TEST_EVIDENCE"
HAOS_TEST_TEMP="$(mktemp -d)"
HAOS_TEST_HTTP_PID=""
finish() {
  if [[ -n "$HAOS_TEST_HTTP_PID" ]]; then kill "$HAOS_TEST_HTTP_PID" 2>/dev/null || true; fi
  # Keep failed VM disks locally for diagnosis; GitHub removes the disposable runner later.
  echo "Disposable VM directory: $HAOS_TEST_TEMP"
}
trap finish EXIT
cd "$HAOS_TEST_TEMP"
mkdir iso
7z e -oiso "$HAOS_TEST_ISO" images/pxeboot/vmlinuz images/pxeboot/initrd.img EFI/BOOT/grub.cfg >/dev/null
HAOS_TEST_KS="$(sed -n 's/.*inst.ks=[^ ]*:\([^ ]*\.ks\).*/\1/p' iso/grub.cfg | head -n 1)"
if [[ -z "$HAOS_TEST_KS" ]]; then
  HAOS_TEST_KS="$(7z l -ba "$HAOS_TEST_ISO" | awk '{print $NF}' | awk '/\.ks$/ {print; exit}')"
fi
[[ -n "$HAOS_TEST_KS" ]] || { echo "Missing kickstart in the built ISO" >&2; exit 1; }
7z e -oiso "$HAOS_TEST_ISO" "${HAOS_TEST_KS#/}" >/dev/null
cp "iso/$(basename "$HAOS_TEST_KS")" ks.cfg
cp "$HAOS_TEST_GUEST_PROBE" haos_guest.py
cp "$HAOS_TEST_REPO/tests/e2e/haos_guest_diagnostics.py" haos_guest_diagnostics.py
cat >>ks.cfg <<'KS'
text
lang en_US.UTF-8
keyboard us
timezone UTC --utc
ignoredisk --only-use=vda
zerombr
clearpart --all --initlabel --disklabel=gpt --drives=vda
autopart --type=btrfs --noswap
bootloader --append="console=tty0 console=ttyS0,115200"
rootpw --lock
poweroff
%post --erroronfail
mkdir -p /var/lib/haos-acceptance
touch /var/lib/haos-acceptance/disposable-ci-guest
curl --fail --retry 3 http://10.0.2.2:8000/haos_guest.py -o /var/lib/haos-acceptance/haos_guest.py
curl --fail --retry 3 http://10.0.2.2:8000/haos_guest_diagnostics.py -o /var/lib/haos-acceptance/haos_guest_diagnostics.py
cat >/etc/systemd/system/haos-acceptance.service <<'UNIT'
[Unit]
Description=Disposable QEMU acceptance probe
Wants=haos-hermes.service haos-controller.service greetd.service
After=haos-hermes.service haos-controller.service greetd.service herald-os-firstboot.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /var/lib/haos-acceptance/haos_guest.py
ExecStopPost=/usr/bin/python3 /var/lib/haos-acceptance/haos_guest_diagnostics.py
StandardOutput=journal+console
StandardError=journal+console
# Multiple actual Hermes starts, encrypted snapshots and both volume modes are
# CPU-heavy under TCG. Keep this below the host's 30-minute boot deadline, with
# room for firstboot, bounded failure diagnostics and shutdown. Production unit
# deadlines and every guest assertion remain unchanged.
TimeoutStartSec=20min
TimeoutStopSec=60s
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -s /etc/systemd/system/haos-acceptance.service /etc/systemd/system/multi-user.target.wants/haos-acceptance.service
%end
KS
cp ks.cfg "$HAOS_TEST_EVIDENCE/kickstart.cfg"
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
qemu-img create -f qcow2 system.qcow2 40G
HAOS_TEST_QEMU=( -smp 2 -m 6144 -machine q35
  -smbios type=1,manufacturer=HAOS-CI,product=haos-acceptance
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
  -drive if=pflash,format=raw,file=vars.fd
  -drive file=system.qcow2,format=qcow2,if=none,id=system
  -device virtio-blk-pci,drive=system,serial=HAOS-CI-SYSTEM,bootindex=1
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0
  -display none -device virtio-vga -no-reboot)
python3 -m http.server 8000 >"$HAOS_TEST_EVIDENCE/http.log" 2>&1 &
HAOS_TEST_HTTP_PID=$!
HAOS_TEST_LABEL="$(blkid -o value -s LABEL "$HAOS_TEST_ISO")"
run_vm() {
  local stage="$1" seconds="$2" log="$3"
  shift 3
  python3 "$HAOS_TEST_REPO/scripts/haos-qemu-runtime.py" --run --timeout "$seconds" --serial-log "$log" \
    "$HAOS_TEST_EVIDENCE/runtime-$stage.json" -- "${HAOS_TEST_QEMU[@]}" "$@" -serial "file:$log"
}
run_vm install 7200 "$HAOS_TEST_EVIDENCE/install.log" -drive "file=$HAOS_TEST_ISO,media=cdrom,readonly=on" \
  -kernel iso/vmlinuz -initrd iso/initrd.img \
  -append "inst.stage2=hd:LABEL=$HAOS_TEST_LABEL inst.ks=http://10.0.2.2:8000/ks.cfg inst.text console=ttyS0,115200"
rg -qi 'reboot: Power down|Power down' "$HAOS_TEST_EVIDENCE/install.log"
# The installer never sees the data disks. Each filesystem is created in a fresh regular file.
for disk in a b c; do
  truncate -s 256M "data-$disk.raw"
  [[ -f "data-$disk.raw" && ! -b "data-$disk.raw" ]]
done
mkfs.ext4 -F -U 42514251-0000-4000-8000-000000000001 data-a.raw >/dev/null
mkfs.ext4 -F -U 42514251-0000-4000-8000-000000000002 data-b.raw >/dev/null
mkfs.ext4 -F -U 42514251-0000-4000-8000-000000000003 data-c.raw >/dev/null
for stage in 1 2; do
  # The removable fixture exists on boot 1 and is physically absent from boot
  # 2's VM topology. Never detach a live host device or discard its backing file.
  HAOS_TEST_REMOVABLE=()
  if [[ "$stage" == 1 ]]; then
    HAOS_TEST_REMOVABLE=( -drive file=data-c.raw,format=raw,if=none,id=data-c
      -device virtio-blk-pci,drive=data-c,serial=HAOS-CI-DATA-C )
  fi
  run_vm "boot-$stage" 1800 "$HAOS_TEST_EVIDENCE/boot-$stage.log" \
    -drive file=data-a.raw,format=raw,if=none,id=data-a -device virtio-blk-pci,drive=data-a,serial=HAOS-CI-DATA-A \
    -drive file=data-b.raw,format=raw,if=none,id=data-b -device virtio-blk-pci,drive=data-b,serial=HAOS-CI-DATA-B \
    "${HAOS_TEST_REMOVABLE[@]}"
  python3 - "$HAOS_TEST_EVIDENCE/boot-$stage.log" "$stage" "$HAOS_TEST_EVIDENCE" <<'PY'
import json, re, sys
from pathlib import Path
log, stage, output = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
assert 'HAOS_ACCEPTANCE_FAILED' not in log.read_text(errors='replace'), 'guest assertions failed'
reports = re.findall(r'HAOS_ACCEPTANCE_JSON=(\{[^\r\n]+\})', log.read_text(errors='replace'))
assert reports, 'no completed acceptance receipt from the real guest'
report = json.loads(reports[-1])
assert report['stage'] == stage
(output / f'acceptance-{stage}.json').write_text(json.dumps(report, indent=2) + '\n')
PY
done
