#!/usr/bin/env python3
"""Run Fedora livecd-creator with a runtime iVentoy GRUB compatibility shim.

The distro's installed Python implementation varies across Fedora releases;
patch its *generated* EFI menu, not brittle snippets of source code.
No host RPM/package files are modified. The shim runs in the exact Python
process that builds the ISO, before the EFI FAT image is assembled.
"""
import re
import runpy
import sys

BAD_COMMANDS = re.compile(r"(?m)^(\s*)(linuxefi|initrdefi)(?=\s)")
LINUX_LINE = re.compile(r"(?m)^\s*linux\s+/[^\n]*vmlinuz")
INITRD_LINE = re.compile(r"(?m)^\s*initrd\s+/[^\n]*initrd")


def fix_grub_text(menu: str) -> str:
    """Replace only GRUB commands at the beginning of menu lines."""
    commands = {"linuxefi": "linux", "initrdefi": "initrd"}
    updated = BAD_COMMANDS.sub(lambda m: m.group(1) + commands[m.group(2)], menu)
    if not LINUX_LINE.search(updated) or not INITRD_LINE.search(updated):
        raise ValueError("EFI GRUB stanza lacks linux/initrd kernel boot lines")
    if BAD_COMMANDS.search(updated):
        raise ValueError("Incompatible GRUB commands survived conversion")
    return updated



# iVentoy's virtual ISO block device can vanish in dracut. Fetch live SquashFS
# over the iVentoy HTTP service rather than requiring this block device.
PXE_HTTP_STANZA = """
menuentry 'Start HAOS via iVentoy HTTP (network root)' --class gnu-linux --class os {
    echo 'iVentoy server IP (e.g. 192.168.50.1):'
    read haos_server
    echo 'iVentoy image ID (from iVentoy ISO Management):'
    read haos_image_id
    if [ -z "$haos_server" -o -z "$haos_image_id" ]; then
        echo 'Missing server IP or image ID; returning to menu.'
        sleep 4
    else
        linux /isolinux/vmlinuz0 root=live:http://__SERVER__:16000/eiso/id/__ID__/LiveOS/squashfs.img ip=dhcp rd.neednet=1 rd.live.image ro
        initrd /isolinux/initrd0.img
    fi
}
""".replace("__SERVER__", "${haos_server}").replace("__ID__", "${haos_image_id}")


def add_iventoy_network_boot(menu: str) -> str:
    """Extra opt-in PXE boot, without altering conventional USB ISO entry."""
    if "Start HAOS via iVentoy HTTP (network root)" in menu:
        raise ValueError("Duplicate iVentoy HTTP menu entry")
    if not LINUX_LINE.search(menu) or not INITRD_LINE.search(menu):
        raise ValueError("Cannot add HTTP boot to invalid EFI GRUB menu")
    return menu.rstrip() + "\n" + PXE_HTTP_STANZA

def install_runtime_shim() -> dict:
    from imgcreate.live import x86LiveImageCreator

    name = "_x86LiveImageCreator__get_efi_image_stanzas"
    original = getattr(x86LiveImageCreator, name, None)
    if original is None:
        raise RuntimeError("Fedora's EFI GRUB stanza generator is unavailable")
    calls = {"count": 0, "rewrites": 0}

    def compatible_stanzas(self, *args, **kwargs):
        raw = original(self, *args, **kwargs)
        if not isinstance(raw, str):
            raise TypeError("Fedora EFI menu generator returned non-text output")
        corrected = add_iventoy_network_boot(fix_grub_text(raw))
        calls["count"] += 1
        if corrected != raw:
            calls["rewrites"] += 1
        print(
            f"HAOS EFI GRUB stanza #{calls['count']}: "
            f"standard linux/initrd; rewritten={corrected != raw}",
            flush=True,
        )
        return corrected

    setattr(x86LiveImageCreator, name, compatible_stanzas)
    return calls


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: fix_livecd_grub.py [livecd-creator options]")
    calls = install_runtime_shim()
    sys.argv = ["/usr/bin/livecd-creator", *sys.argv[1:]]
    try:
        runpy.run_path("/usr/bin/livecd-creator", run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code == 0 and calls["count"] == 0:
            raise RuntimeError("Build exited successfully but no EFI GRUB menu was generated")
        raise
    if calls["count"] == 0:
        raise RuntimeError("No EFI GRUB menu was generated")


if __name__ == "__main__":
    main()
