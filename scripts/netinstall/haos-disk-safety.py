#!/usr/bin/env python3
"""Refuse USB, removable, undersized and read-only installation targets.

The same live ISO boots via USB and iVentoy. A USB credential stick must
never appear among eligible HAOS installation disks.
"""
import json
import subprocess
import sys

MIN_INSTALL_BYTES = 16 * 1024 ** 3

def is_eligible(device):
    if device.get("type") != "disk":
        return False
    if not str(device.get("path") or "").startswith("/dev/"):
        return False
    try:
        size = int(device.get("size") or 0)
        removable = int(device.get("rm") or 0)
        read_only = int(device.get("ro") or 0)
    except (ValueError, TypeError):
        return False
    transport = str(device.get("tran") or "").lower()
    return size >= MIN_INSTALL_BYTES and removable == 0 and read_only == 0 and transport != "usb"

def inspect():
    cp = subprocess.run(
        ["lsblk", "--json", "--bytes", "--nodeps", "--paths",
         "--output", "PATH,TYPE,SIZE,TRAN,RM,RO,MODEL"],
        check=True, capture_output=True, text=True, timeout=15
    )
    return json.loads(cp.stdout).get("blockdevices", [])

def main(args):
    if args == ["list"]:
        eligible = [item for item in inspect() if is_eligible(item)]
        for dev in eligible:
            print(f'{dev["path"]}    {int(dev["size"]) // (1024**3)}GiB    {dev.get("model") or "Internal disk"}')
        if not eligible:
            print("NO ELIGIBLE INTERNAL DISK: USB credentials drive is NOT an install target.", file=sys.stderr)
            print("Check BIOS Intel VMD / RST settings and NVMe kernel detection.", file=sys.stderr)
            return 2
        return 0
    if len(args) == 2 and args[0] == "check":
        target = args[1]
        if any(dev.get("path") == target and is_eligible(dev) for dev in inspect()):
            print(f"Internal target verified: {target}")
            return 0
        print(f"REJECTED installation disk: {target}", file=sys.stderr)
        return 1
    print("Usage: haos-disk-safety.py list | check /dev/internal-disk", file=sys.stderr)
    return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
