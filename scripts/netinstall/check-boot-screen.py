#!/usr/bin/env python3
"""Assert a QEMU UEFI screenshot contains the custom HAOS graphical UI accent."""
import sys
from pathlib import Path
from PIL import Image

def main():
    p = Path(sys.argv[1])
    if not p.is_file():
        return 1
    with Image.open(p) as source:
        im = source.convert("RGB")
        # Cyan is a deliberately unique UI accent, distinct from firmware/GRUB.
        pixels = sum(1 for r,g,b in im.getdata() if g >= 195 and b >= 165 and r <= 125)
    print(f"HAOS graphical UI candidate pixels: {pixels}", flush=True)
    return 0 if pixels >= 800 else 1

if __name__ == "__main__":
    sys.exit(main())
