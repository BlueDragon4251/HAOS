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

## HTTP-root fallback for iVentoy PXE

When booted over iVentoy, a VM or physical PC may have the HAOS GRUB menu
and kernel but lose access to the virtual ISO drive at dracut startup.
The symptom is waiting indefinitely for
`/dev/disk/by-label/HAOS-DUAL-44`.

Use the optional UEFI GRUB entry **Start HAOS via iVentoy HTTP (network root)**.
It asks for the iVentoy **server IP** and **image ID**, both short values
available from iVentoy ISO Management (web UI often port 26000).

The live system is downloaded directly from the ISO already on your
iVentoy server, via its documented HTTP ISO-internal-file endpoint:
`http://SERVER:16000/eiso/id/IMAGE_ID/LiveOS/squashfs.img`.
No duplicate storage of the ~1.5 GB ISO is needed. Check the URL is
reachable before booting. iVentoy must serve the ISO internal files and
the client must have working wired DHCP.

If the URL does not work, the live OS cannot boot in this mode. This is an
**untested real-hardware fallback** rather than confirmed PXE installation.
Standard USB boot remains unchanged. Never host GHCR tokens via this HTTP
service; token transport still requires USB, trusted HTTPS, or manual input.

## On-device installer input and screen recovery

The new GUI sizes itself from the actual X11 screen mode, starts Openbox
before Tkinter, and attempts to take keyboard focus. It supports a physical
mouse/touchpad and also provides a keyboard-only operation path:

- `1`: open the public stable installer. Public stable still fails safely
  when no official stable image manifest has been published.
- `2` or `F3`: open NetworkManager text interface in an on-screen terminal.
- `Tab` / `Shift+Tab`, then `Enter`: navigate and activate controls.
- `Ctrl+Shift+D` or `F12`: authenticated private GHCR image chooser.
- `F2` or `Ctrl+Alt+F2`: use the independent HAOS text installer on TTY2.
- `Ctrl+Alt+F1`: return to the graphical installer.
- `Esc`: show the on-screen keyboard shortcuts.

If the pointer/keyboard is completely absent on the HP laptop, try a wired
USB keyboard and mouse and inspect device enumeration. On the live filesystem,
`/run/haos-kiosk/hardware.log` records xrandr display modes, libinput devices,
and the kernel's input device inventory (no GitHub credentials are recorded).
The X11 session logs Openbox startup to `/run/haos-kiosk/openbox.log`.

CI checks screen edge coverage in QEMU, emulates pressing the numeric `2`
key, and requires a material on-screen change after the network-settings
window opens. Those checks cannot conclusively verify an HP-specific I2C
touchpad. Test both direct USB boot and iVentoy HTTP PXE boot before declaring
the installer release-ready.
