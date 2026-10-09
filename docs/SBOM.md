# Image software inventory

The HAOS image build now scans the actual image before producing its installer.
Syft 1.54.1 is pinned to its official container digest
`sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa`.
The scan runs as the runner's non-root UID in a read-only container with no network,
no Linux capabilities, two CPUs and a 3 GiB limit. Its only inputs/output mounts
are the newly exported OCI archive (read-only) and this build's evidence directory.
The archive is removed before ISO generation; scanning has a separate 20-minute
timeout. It neither executes software from the cataloged image nor connects to a
model/provider or vulnerability service.

Evidence includes:

- `image.cdx.json`: CycloneDX 1.6 final-image package/file catalog.
- `image.syft.json`: the original source/image/tool metadata and detailed catalog.
- `npm.raw.cdx.json`: the pinned npm 10.9.4 build graph, CycloneDX 1.5.
- `npm.cdx.json`: that graph with equivalent package occurrences normalized.
- Actual image Python freeze/hash requirements and RPM epoch/version/architecture
  inventory, including RPM key pseudo-packages.
- `sbom-index.json`: exact source commit, image ID, scanner/npm versions, document
  SHA-256 values, checked inventory counts and explicit remaining limitations.

The verifier requires the catalog's source version/image ID to equal this build.
Every frozen Python version must be actually installed, every installed Python
version must appear in the image catalog, and every installed RPM must match its
name, epoch/version and architecture. Epoch PURL qualifiers are preserved; absent
architecture on RPM public-key records is normalized from RPM's `(none)` without
discarding the record. Empty inventories, wrong images/tool versions, missing
packages or incompatible component references fail the image job. The build
manifest embeds the verified index; checksum/metadata uploads retain all documents.

npm 10.9.4 sometimes repeats one package reference at two install paths. The
normalizer retains both location properties and every actual dependency edge,
and refuses a conflicting identity/version/hash/other component field. The raw
graph remains alongside it, and verification recomputes the normalization to
detect changes or lost evidence. Local npm 11.9.0 rejected the intentional existing
`xml2js`/`node-gyp` security overrides; the supported pinned CLI generates the
actual graph without removing those overrides or suppressing errors.

Local negative contracts cover foreign source/tool identity, missing Python
versions, different RPM architecture/epoch, empty graphs, ambiguous references
and conflicting duplicate npm records. Actual offline scanner/verification probes
also ran through both Docker and OCI archive readers on a disposable Fedora 44
catalog fixture: its actual RPM database (147 records) plus 80 copied **actual
installed Python distribution metadata** directories. The copied directories test
cataloging, not execution of a Hermes image. The separate actual build npm graph
contains 188 unique package identities; its repeated `long@5.3.2` occurrence retains
both locations. This is deliberately separate from a real HAOS-image result.

Catalogs and inventories improve release evidence; they do not prove exhaustive
identification of every vendored/embedded C/C++/Rust/Go/WASM component or complete
license/vulnerability review. The npm build graph and image catalog are distinct
documents, not a merged full dependency graph. Hermes model/gateway behavior,
signatures/provenance, reproducible base/builder inputs, installed acceptance,
Secure Boot and physical hardware remain independent release gates. No Stable
release is authorized by a successful catalog.
