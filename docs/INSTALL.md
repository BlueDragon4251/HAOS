# Installation status

No signed, accepted production ISO exists yet. Herald release downloads are not HAOS releases. Development images should be tested in disposable VMs.

haos-image.yml builds the native x86_64 shell, Fedora 44 bootc image and Anaconda ISO. On success its private artifact contains haos-x86_64-development.iso, SHA256SUMS, build-manifest.json, logs, partial npm SBOM and RPM inventory. Failed runs upload logs rather than a fabricated ISO.

```sh
sha256sum -c SHA256SUMS
bash scripts/test-haos-iso.sh /absolute/path/development.iso /absolute/path/evidence
```

The QEMU/OVMF test creates a fresh sparse system disk, installs the exact ISO, then attaches two newly formatted data-disk files. The installer cannot select those data disks. Guest code requires an explicit disposable marker and QEMU product/serial identities. Missing assertion receipts fails the test.

Prerequisites: QEMU, OVMF, p7zip, e2fsprogs, ripgrep; CI requires KVM. The VM uses 4 vCPUs, 6 GiB RAM, 40 GiB sparse system disk. These are test resources, not measured hardware minima. The inherited generic unattended.ks points upstream and is not a HAOS install path.

LUKS2 physical installation, dual boot, Secure Boot, USB writing and GPU compatibility have not passed HAOS acceptance.
