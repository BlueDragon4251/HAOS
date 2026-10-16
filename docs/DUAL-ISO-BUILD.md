# HAOS Dual Channel Live ISO — experimental builder

The separate `haos-dual-iso.yml` workflow attempts to build a Fedora 44 live installer with a TTY1 systemd installer service. Unlike the older Anaconda netinstall, this path includes Podman to pull private GHCR images.

1. **Enter**: public stable image only, resolved from the `main` release manifest. If no validated manifest exists, the installer refuses to proceed. Never use a dev digest as a fallback.
2. **:dev**: interactive GHCR token and digest-pinned private image.
3. Select an entire target disk and confirm twice before destruction.

The menu uses a text TTY rather than a graphical installer. This is a prototype, not release-ready. A private token is not embedded in the ISO. The path must pass a real CI image compose, UEFI boot, network/AX211 hardware checks, destructive install in an expendable VM disk, first and second boot, and private update authentication tests.

**Important:** The hidden entry is discoverability only, not authorization. GHCR token remains the actual access control.

The ISO-size goal of 150–300 MB is not proven. Podman, live kernel, firmware, and bootc may exceed this target.

## Developer credentials: USB and iVentoy PXE

Every HAOS live installer has the same hidden `:dev` access regardless of whether its ISO boots from USB or iVentoy PXE. Inside the development path choose one of three sources: USB, HTTPS endpoint, or manual entry.

**USB:** Create a separate USB partition (FAT32 works) and place a plain text GitHub package-read token as the first line in `HAOS-DEV/token.txt`. The installer mounts the selected USB partition read-only and unmounts it after reading. Keep the stick physically secure and remove it after use. Never place this token on the installation target disk.

**iVentoy:** Put `haos-dual-channel-x86_64.iso` under iVentoy's `iso/` directory. iVentoy can PXE-boot it. The installer does not automatically inherit credentials from the PXE server; select either the USB method or an independent, authenticated **HTTPS** credentials URL. iVentoy's built-in `http://<server>:16000/user/...` serves arbitrary files without TLS and must **never** be used to host a GHCR token. Use an HTTPS gateway with restricted access and preferably a short-lived token URL.

**Safety:** No credentials are included in the ISO, GitHub Actions artifacts, or the installed system. The installer clears its temporary authfile on exit. For private subsequent updates, a separate credentials mechanism will be required.

This integration has not yet passed a real PXE boot or GHCR private-install acceptance test.
