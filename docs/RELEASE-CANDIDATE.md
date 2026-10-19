# HAOS integrated development candidate

This document is an **acceptance contract**, not a statement that the
whole OS is finished. GitHub Actions publishes independent outputs from the
same source revision; stale artifacts from older commits never count as a
source-matched release. The branch is `agent/haos-foundation` and PR #1
remains a draft.

| Required evidence | GitHub Actions workflow | Output |
| --- | --- | --- |
| Android Kotlin tests and APK | HAOS Native Android Mobile | `haos-mobile-debug-apk` + SHA256SUMS |
| UEFI graphical Live ISO | HAOS Dual-Channel Live ISO (release candidate tests) | `haos-dual-channel-iso-<sha>` + SHA256SUMS |
| Online image and smaller legacy Anaconda ISO | HAOS Netinstall (GHCR + small online installer) | `haos-netinstall-x86_64-<sha>` and `ghcr.io/bluedragon4251/haos@sha256:<digest>` |
| Full image-embedded ISO with installed two-boot QEMU gates | HAOS x86_64 image and installer build | `haos-qemu-acceptance-<sha>` plus ISO/build evidence |
| Cross-platform application/security/unit suites | CI; HAOS services and kernel boundaries | All required jobs green |

The workflow `HAOS immutable tri-artifact qualification` can be
**manually dispatched** with the exact 40-digit source SHA. It fails
closed if any required workflow has no completed successful run for that
SHA or if a required corresponding artifact is missing/expired. **Passing
this gate does not mark the software production-safe**: the Android APK
is still a debug build, releases are unsigned and functionality may be
incomplete.

## Installation paths

- **Dual-Channel Live ISO**: local graphical installer with explicit
  public-stable selection or authenticated private GHCR developer
  channel. Booting and GUI navigation do **not** prove actual disk
  installation. The stable option cannot work until an owner
  explicitly publishes and validates a signed public stable image
  manifest; do not substitute a development tag.
- **Legacy Fedora Anaconda netinstall ISO**: requires the OCI image to
  be anonymously readable. Its default GitHub package may be
  private. It does **not** include the dual-channel authenticated
  installer. Do not assume success based on the ISO's build status.
- **Offline bootc ISO**: independent installation in disposable
  QEMU with two reboot receipts. Never install against a real disk
  without explicit backup and owner acceptance.

## Hardware acceptance still required

Boot/install from **the exact SHA-qualified candidate** on a
disposable or backed-up HP target; verify UEFI or BIOS boot, correct
SSD selection and explicit wipe confirmation, Intel Wi-Fi AX211/Bluetooth,
audio, real login/owner recovery, power and reboot persistence, network,
local PKI pairing, and device-specific graphics.

## Software and environmental blockers *in addition* to HP tests

Real provider/gateway/GitHub mission credentials, durable autonomous
Git/parallel worktree jobs, comprehensive remote desktop and input,
secure WAN reachability and wake behind Drei CGNAT, LUKS/hotplug,
hardware platform variations, fully validated whole-system/off-host
recovery, stable update rollback, complete security review,
reproducible signed OCI/ISO and release-signed Android APK.

No pipeline should silently mark these as done. Keep Issue #2
accurate; never merge draft PR #1 or publish a Stable release from
an unqualified prototype.
