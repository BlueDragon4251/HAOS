#!/usr/bin/env python3
"""Correct incompatible linuxefi/initrdefi in Fedora livecd-tools' EFI template.

Fedora LiveImageCreator emits linuxefi/initrdefi in its GRUB menu. iVentoy's
UEFI GRUB 2.04 may lack those commands; standard GRUB linux/initrd works.
We patch the generator BEFORE ISO creation so both ISO and EFI FAT copy agree.
Fail closed if Fedora changes the template instead of writing a broken ISO.
"""
import importlib.util
from pathlib import Path


def fix_source(source: str) -> str:
    replacements = {
        "%(tab)slinuxefi ": "%(tab)slinux ",
        "%(tab)sinitrdefi ": "%(tab)sinitrd ",
    }
    for before, after in replacements.items():
        count = source.count(before)
        if count != 1:
            raise ValueError(f"Expected exactly one {before!r} in livecd-tools, found {count}")
        source = source.replace(before, after)
    return source


def main() -> None:
    spec = importlib.util.find_spec("imgcreate.live")
    if spec is None or spec.origin is None:
        raise RuntimeError("Cannot locate installed Fedora imgcreate.live module")
    path = Path(spec.origin)
    source = path.read_text(encoding="utf-8")
    patched = fix_source(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched EFI GRUB menu generator: {path}", flush=True)


if __name__ == "__main__":
    main()
