# HAOS stable and developer channels (work in progress)

`scripts/netinstall/haos-install.sh` is a TTY launcher for a trusted Fedora Live environment.

**Standard:** enter 1 (or Enter). It requests an explicitly published, digest-pinned public stable image at `https://raw.githubusercontent.com/BlueDragon4251/HAOS/main/releases/stable-image.txt`. If this file is not available, installation refuses to proceed. This is intentional: a development image must never be silently promoted to stable.

**Developer:** type `:dev` at the selection prompt, then paste an immutable private GHCR image digest. The separate script prompts without echo for a username and GHCR read token and removes the temporary auth material on exit.

Both paths ask for an entire physical disk and demand two explicit destructive confirmations. This is not an access-control boundary: any person with the USB can access the developer entry. Private GHCR requires valid credentials.

**Not yet a completed standalone ISO integration:** The Fedora 44 Anaconda ISO cannot install from an authenticated registry. The current `mkksiso` pipeline does not boot the launcher or ship a podman-ready live environment. A dedicated live stage2, GRUB entry, initramfs/firmware, automatic launcher startup and full UEFI/QEMU + hardware acceptance are still required. Do not treat the existing `haos-netinstall-x86_64.iso` as dual-mode.
