#!/usr/bin/env python3
"""Verify that a built ISO's EFI GRUB cfg works with standard GRUB commands."""
from pathlib import Path
import re
import sys


def verify(contents: str) -> None:
    if re.search(r"(?m)^\s*(?:linuxefi|initrdefi)(?=\s|$)", contents):
        raise ValueError("Incompatible GRUB linuxefi/initrdefi command found")
    if not re.search(r"(?m)^\s*linux\s+/[^\n]*vmlinuz", contents):
        raise ValueError("Missing standard GRUB linux kernel command")
    if not re.search(r"(?m)^\s*initrd\s+/[^\n]*initrd", contents):
        raise ValueError("Missing standard GRUB initrd command")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_live_grub.py <grub.cfg> [<grub.cfg>...]", file=sys.stderr)
        return 2
    for filename in sys.argv[1:]:
        try:
            verify(Path(filename).read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"FAIL {filename}: {exc}", file=sys.stderr)
            return 1
        print(f"PASS {filename}: standard GRUB linux/initrd present", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
