# Release gates

No production release is approved. Development artifacts are private/unsigned. SHA-256 verifies bytes against a manifest, not signer identity or safe behavior.

Manifest records source/repository, architecture, Herald/Hermes pins, OCI/base metadata and checksum. npm CycloneDX plus RPM inventory is partial evidence, not a complete Python/system/application SBOM. Mutable base/builder tags prevent full reproducibility claims.

Release requires exact-ISO QEMU receipts, all master-prompt acceptance, owner/storage/egress review, dependency checks, complete SBOM/provenance, changelog and honest limitations. Signing needs a protected owner-managed key or approved keyless identity policy; no identity/key is invented or committed.

Secure Boot needs verified firmware/bootloader/kernel trust and enrollment, beyond OCI/checksum signing. Private update registry access needs a tested installed-machine design. Keep draft PR #1 unmerged while critical gates fail; preserve and fix failures.
