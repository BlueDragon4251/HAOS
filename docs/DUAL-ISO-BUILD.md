# HAOS Dual Channel Live ISO — experimental builder

The separate `haos-dual-iso.yml` workflow attempts to build a Fedora 44 live installer with a TTY1 systemd installer service. Unlike the older Anaconda netinstall, this path includes Podman to pull private GHCR images.

1. **Enter**: public stable image only, resolved from the `main` release manifest. If no validated manifest exists, the installer refuses to proceed. Never use a dev digest as a fallback.
2. **:dev**: interactive GHCR token and digest-pinned private image.
3. Select an entire target disk and confirm twice before destruction.

The menu uses a text TTY rather than a graphical installer. This is a prototype, not release-ready. A private token is not embedded in the ISO. The path must pass a real CI image compose, UEFI boot, network/AX211 hardware checks, destructive install in an expendable VM disk, first and second boot, and private update authentication tests.

**Important:** The hidden entry is discoverability only, not authorization. GHCR token remains the actual access control.

The ISO-size goal of 150–300 MB is not proven. Podman, live kernel, firmware, and bootc may exceed this target.
