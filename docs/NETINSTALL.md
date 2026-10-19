# HAOS Netinstall (development)

HAOS now has two separate installation paths:

1. **Online/Netinstall:** a smaller Fedora 44 Everything Netinstall UEFI ISO.
   It contains Anaconda and installer drivers **but not the HAOS system image**.
   During installation, Anaconda fetches the HAOS Fedora-bootc OCI image from a registry.
2. **Offline:** the previous large image-embedded bootc installer and its QEMU
   acceptance flow remain unchanged.

This is a **development path**, not a stable/released installation. On the
`agent/haos-foundation` branch, [the Netinstall workflow](../.github/workflows/haos-netinstall.yml)
builds a fresh OCI image in a disposable GitHub runner, pushes the **dev-<commit>**
tag to `ghcr.io/bluedragon4251/haos`, records the remote **sha256 digest**, and
makes a separate Fedora netinstall ISO with that digest as its immutable source.
Neither large OCI layers nor a local server need to be stored on your laptop.

## Download and install

1. Wait for the workflow **HAOS Netinstall (GHCR + small online installer)** to
   finish. Download the `haos-netinstall-x86_64-<commit>` workflow artifact in
   GitHub Actions. It includes the ISO, `SHA256SUMS`, `IMAGE.txt`, and the
   generated Kickstart. Artifacts expire after 14 days.
2. On GitHub go to your profile/organization **Packages → haos → Package settings →
   Change visibility → Public**. GHCR packages can be private initially even
   if a repository is public. **Anonymous pulls will not work until public**.
   This action needs a human owner; CI must not assume it has happened.
3. Verify the downloaded ISO checksum using `sha256sum -c SHA256SUMS` from the
   same directory, flash to USB, and boot your test PC.
4. At the GRUB boot screen, the default installation image is already bound to
   that build's **immutable OCI sha256 digest**. For another image, press **e**
   at the boot menu, add `haos.image=registry.example.com/namespace/image@sha256:<64hex>`
   to the **linux kernel** line, then start the modified entry with the key
   shown by GRUB (often Ctrl+X or F10). The source field accepts an **OCI registry
   reference**, not a generic HTTP file download URL, and requires a digest.
5. In Anaconda, configure your **network (Ethernet or Wi-Fi)** and use its
   **interactive storage screen** to choose your target disk/partitions.
   Nothing is automatically wiped by this Netinstall Kickstart.
6. Wait for Anaconda to pull the public OCI image and finish installing HAOS.
   Disconnect the installation medium and restart into the installed system.

Fedora's installer includes its own kernel/firmware set and may differ from
the installed HAOS image. The **HAOS OCI image** includes Intel AX211 firmware
(`iwlwifi-mvm-firmware`, `iwlwifi-mld-firmware`), Bluetooth firmware, and
`alsa-sof-firmware` through `linux/image/packages.txt`. Verify Wi-Fi during
the installer **and** again after the installed boot. Installer-side AX211
firmware availability is not yet proven on physical hardware.

## Safety and scope

- Fedora **44** Anaconda's `bootc --source-imgref=registry:...` Kickstart command
  is used. Its network-registry support does **not** extend to authenticated
  registries in this mode. Therefore GHCR must be public for this flow.
- The default image source is **a digest**, so the installer does not silently
  install a later `:latest` image. Changing the boot source is an explicit,
  owner-controlled action.
- A digest checks content identity, **not publisher authenticity**. Development
  images are **unsigned**, and neither a signed image trust chain nor a
  Netinstall boot/GUI/disk/installed-guest E2E receipt exists yet.
- No automatic disk erasure, `clearpart`, `zerombr`, or `autopart` is
  included. Always back up data before installing.
- The GitHub workflow uses Fedora Everything 44 (1.7), validated against the
  exact sha256 in Fedora's published signed CHECKSUM. The resulting Netinstall
  media is approximately **1.1 GiB plus customization**, not a guaranteed
  sub-500MB installer. The complete HAOS image lives remotely on GHCR.
- GH Actions storage is temporary. The public GitHub Container Registry is a
  hosted service; check GitHub's then-current registry usage policy and public
  package settings. No personal laptop disk storage or self-hosted server needed
  for the image build or hosting.
- Leave existing full ISO and its acceptance pipeline untouched. When CI can
  safely execute a **fresh Netinstall QEMU** with a public registry image,
  collect proof of UEFI boot, Anaconda source selection, installation and both
  installed boots before treating this as generally usable.
