# Private HAOS installer (experimental)

This is a **first-stage installer script**, NOT yet a standalone bootable 150–300 MB HAOS ISO.
It is intended for a *trusted Fedora Live environment* with Podman, UEFI boot, network and a working Wi-Fi firmware stack.

## Use

1. Boot a supported Fedora Live USB, connect to the network, install Podman if not present.
2. Download/copy `scripts/netinstall/private-install.sh` from the HAOS repository and verify it against a trusted commit.
3. Retrieve the immutable `oci_source` digest from a matching CI `IMAGE.txt`. Run:
   `sudo bash private-install.sh ghcr.io/bluedragon4251/haos@sha256:<exact-64-hex>`
4. Enter a GitHub username and a least-privilege GHCR *read-only* token when prompted. **Never put credentials in kernel arguments, scripts, URLs, commits, or CI logs.**
5. Select a whole physical disk, confirm the exact path, and finally type `WIPE`. **All existing data will be erased.**

## Security and limitations

- Credentials are stored in a private root-only file under `/run` and removed on shell exit. This is temporary only; it cannot make the package public.
- The image is pinned to a SHA-256 digest. Digest identity is **not publisher signature verification**.
- bootc's simple `to-disk` path overwrites the selected disk and does not offer Anaconda's interactive partition customization. It does not preserve other systems.
- This calls `--skip-fetch-check` because private GHCR access is temporary. **Automatic updates will not work** after reboot until a read-only pull secret is securely configured for the installed system (e.g. /etc/ostree/auth.json). Do not copy the installer token blindly.
- Physical UEFI, EFI bootloader, Wi-Fi, disks, first boot and recovery on the HP laptop remain UNTESTED for this path.
- This script does **not** fix the existing Fedora Anaconda ISO's unauthenticated `bootc --source-imgref` flow; do not mark that ISO private-install capable.
- Do not distribute private GHCR tokens as part of the ISO.
