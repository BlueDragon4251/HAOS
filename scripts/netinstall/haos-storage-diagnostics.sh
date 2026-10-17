#!/usr/bin/env bash
# Read-only diagnostic view. No formatting, partitioning or bootc commands.
set -u
echo "HAOS STORAGE DIAGNOSTICS - SAFE / NON-DESTRUCTIVE"
echo "Boot source: USB or iVentoy PXE"
echo
echo "=== Storage kernel modules ==="
for module in nvme nvme_core vmd; do
  echo "Module $module:"
  modprobe "$module" 2>&1 || true
done
udevadm settle --timeout=15 2>/dev/null || true
echo
echo "=== Block devices, partitions, transport and size ==="
lsblk -e7 -o NAME,PATH,SIZE,TYPE,TRAN,RM,RO,MODEL,FSTYPE,MOUNTPOINTS || true
echo
echo "=== PCI storage controllers ==="
if command -v lspci >/dev/null; then
  lspci -nnk | grep -Ei -A 4 'vmd|nvme|non-volatile|sata|storage|raid' || true
else
  echo "lspci is unavailable"
fi
echo
echo "=== NVMe controllers ==="
if command -v nvme >/dev/null; then nvme list || true; fi
echo
echo "=== Eligible installation targets ==="
python3 /usr/local/sbin/haos-disk-safety.py list || true
echo
echo "=== Recent driver messages ==="
dmesg | grep -Ei 'vmd|nvme|pcie|ahci|rst' | tail -70 || true
echo
echo "Never choose the USB credentials drive as a target."
