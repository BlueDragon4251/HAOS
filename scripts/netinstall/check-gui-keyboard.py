#!/usr/bin/env python3
"""Check that the QEMU keyboard can change the installer UI, not just draw it."""
from PIL import Image, ImageChops
import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: check-gui-keyboard.py before.ppm after.ppm", file=sys.stderr)
        return 2
    try:
        with Image.open(sys.argv[1]) as original, Image.open(sys.argv[2]) as newer:
            before, after = original.convert("RGB"), newer.convert("RGB")
            if before.size != after.size:
                print(f"Display size changed after keyboard input: {before.size} -> {after.size}")
                return 0
            # Sample every 3 pixels to avoid large (1920x1080) PPM comparisons.
            dif = ImageChops.difference(before, after)
            changed = sum(
                1 for pixel in list(dif.getdata())[::3]
                if max(pixel) >= 45
            )
            print(f"Keyboard interaction changed sampled pixels: {changed}", flush=True)
            if changed < 6000:
                print("ERROR: Network-settings hotkey did not visibly open a window", file=sys.stderr)
                return 1
            return 0
    except Exception as e:
        print(f"ERROR: no valid QEMU screenshot after keyboard press: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
