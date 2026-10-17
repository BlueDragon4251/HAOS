#!/usr/bin/env python3
"""Verify the HAOS kiosk is visible and fills the entire QEMU display."""
import sys
from pathlib import Path
from PIL import Image

BG = (7, 13, 28)


def verify(image):
    image = image.convert("RGB")
    width, height = image.size
    if width < 320 or height < 240:
        raise ValueError(f"Unexpected VGA screen size {width}x{height}")
    cyan = sum(1 for red, green, blue in image.getdata()
               if green >= 195 and blue >= 165 and red <= 125)
    if cyan < 800:
        raise ValueError(f"No HAOS UI cyan elements detected (pixels={cyan})")
    # An unmaximized 1200x740 Tk window used to leave black borders on large
    # screens. Its fullscreen should have the HAOS blue background at all edges.
    locations = [
        (5, 5),
        (width - 6, 5),
        (5, height - 6),
        (width - 6, height - 6),
        (width // 2, height - 6),
    ]
    samples = [image.getpixel(pos) for pos in locations]
    allowed = sum(1 for pixel in samples
                  if max(abs(pixel[i] - BG[i]) for i in range(3)) <= 15)
    print(f"HAOS cyan pixels={cyan}, fullscreen edge matches={allowed}/5, "
          f"screen={width}x{height}, samples={samples}", flush=True)
    if allowed < 4:
        raise ValueError("HAOS kiosk is not covering the QEMU screen")
    return True


def main():
    if len(sys.argv) != 2:
        return 2
    p = Path(sys.argv[1])
    if not p.is_file():
        return 1
    try:
        with Image.open(p) as screenshot:
            verify(screenshot)
        return 0
    except Exception as exc:
        print(f"HAOS UI boot check: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
