# Release gates

No production release is approved. The repository and its development Actions artifacts are public; builds remain unsigned. SHA-256 verifies bytes against a manifest, not signer identity or safe behavior. Public evidence uploads must contain only intentionally disposable fixtures and bounded redacted receipts, never real credentials, chats or desktop captures.

Manifest records source/repository, architecture, Herald/Hermes pins, OCI/base metadata and checksum. The [image SBOM gate](SBOM.md) now adds an actual offline image catalog, preserved/normalized pinned npm graph and exact installed Python/RPM checks with document hashes and source/image IDs. Matching real HAOS-image results and embedded-component/license/vulnerability review remain required before claiming a complete release SBOM. Mutable base/builder tags prevent full reproducibility claims.

Release requires exact-ISO QEMU receipts, all master-prompt acceptance, owner/storage/egress review, dependency checks, complete SBOM/provenance, changelog and honest limitations. Signing needs a protected owner-managed key or approved keyless identity policy; no identity/key is invented or committed.

Secure Boot needs verified firmware/bootloader/kernel trust and enrollment, beyond OCI/checksum signing. Private update registry access needs a tested installed-machine design. Keep draft PR #1 unmerged while critical gates fail; preserve and fix failures.
