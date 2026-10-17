#!/usr/bin/env python3
"""Check the actual xorriso El Torito report (not just GPT/isohybrid flags)."""
from pathlib import Path
import re
import sys

UEFI_ENTRY = re.compile(
    r"^El Torito boot img\s*:\s*\d+\s+UEFI(?:\s|$)", re.MULTILINE
)

def contains_uefi_boot_entry(report: str) -> bool:
    return UEFI_ENTRY.search(report) is not None

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_uefi.py <xorriso-boot-report>", file=sys.stderr)
        return 2
    report = Path(sys.argv[1]).read_text(encoding="utf-8")
    if not contains_uefi_boot_entry(report):
        print("FAIL: xorriso report has no UEFI El Torito boot entry", file=sys.stderr)
        return 1
    print("PASS: xorriso reports a UEFI El Torito boot image")
    return 0

if __name__ == "__main__":
    sys.exit(main())
