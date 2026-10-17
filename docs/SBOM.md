# Image software inventory

The HAOS image build now scans the actual image before producing its installer.
Syft 1.54.1 is pinned to its official container digest
`sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa`.
The scan runs as the runner's non-root UID in a read-only container with no network,
no Linux capabilities, no new privileges, two CPUs, 256 PIDs and a 5 GiB memory/swap limit.
Its mounts are the newly exported OCI layout (read-only), private disk-backed
extraction/cache scratch and this build's evidence directory. Go's soft heap limit
is 1536 MiB with one cataloger worker; catalogers and inventory requirements are retained. All temporary layout/
scratch data and the owned scanner container are removed before ISO generation;
scanning has an 18-minute command deadline and separate 20-minute job-step timeout.
It neither executes software from the cataloged image nor connects to a
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
- `sbom-scanner-status.json`: actual Docker exit/status/OOM flags, captured before
  removing this build's scanner; only an exited, zero-code, non-OOM scan proceeds.
- `sbom-resource-samples.jsonl`: only the owned scanner's aggregate memory, CPU
  and PID samples every 15 seconds, without command arguments, paths or environment.
- `sbom-host-resources.json`: actual host RAM/available RAM, scratch filesystem
  free bytes and scanner limit. Insufficient host memory fails before scanning.

The verifier accepts at most 128 MiB per document and hashes documents in chunks
without another full-file allocation. Its Linux CLI has a separate 2 GiB address-
space limit and retains any smaller enclosing limit. This is a build-tool limit,
not an agent quota. The small `haos-build-metadata-COMMIT` artifact retains the
index, runtime probes and process/resource receipts; full image catalogs live in
`haos-image-sbom-COMMIT` and the complete image/ISO evidence artifact. Large catalogs
must not make bounded metadata inspection download or publish arbitrary image data.

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

The first actual HAOS-image scan at `aeac4ad` ([37988845635](https://github.com/BlueDragon4251/HAOS/actions/runs/37988845635))
exited 137 before catalog verification; its removed container cannot supply an
OOM receipt. A separate disposable image adds a real 512 MiB file to the Fedora
catalog fixture (730,221,056-byte OCI archive). At the same 1 GiB limit and 700 MiB
Go limit, both RAM-scratch and disk-scratch **archive** readers actually report
OOMKilled; the actual **OCI directory** reader completes without OOM. Its unchanged
verifier accepts the exact image ID, all 147 RPM and 80 installed/frozen Python
records and 188 npm identities. The fix therefore changes the supported image
source format and scratch storage, rather than raising/removing the memory limit
or discarding catalogers. Matching HAOS-image verification remains required.

The subsequent actual HAOS image at `bba8f3b` ([37991730553](https://github.com/BlueDragon4251/HAOS/actions/runs/37991730553))
still exceeded 3 GiB even with disk scratch and an OCI layout. Its retained Docker
state proves `exit_code: 137, oom_killed: true`; the small fixture does not substitute
for this failure. The build scanner now reserves 5 GiB only after checking actual
host memory with additional headroom, lowers Go's soft limit to 1536 MiB and uses one worker to reduce concurrent
allocation. No input, cataloger, installed package or verification assertion is
removed. Metrics are recorded before cleanup; successful full-image inventory
verification remains required. This build-tool limit is not a mission budget.

The actual image at `41e58d3758cc11e82690c2097ab683ef426af4fb`
([37994395134](https://github.com/BlueDragon4251/HAOS/actions/runs/37994395134))
completed its scanner with **exit 0, no OOM**, with sampled memory up to 3.645 GiB.
Its 82,145,743-byte Syft document exceeded the old 64 MiB verifier input limit;
the image workflow correctly failed before ISO/installation. The actual ZIP
`11647441671` was downloaded and verified against GitHub SHA256
`da3ebae698f81d7740c9bad1498568747de39eba71c088412db372f67371cb4a`.
The corrected verifier then checked these unchanged real catalogs, source and
image `sha256:9bad188288c408f6ba20ec3ef6f447cc243031578636fcb0ab0acf7660faaec9`:
all **80 installed/frozen Python versions, 1,210 RPM epoch/version/architecture
records and 188 npm build identities** passed. The CycloneDX document is
33,322,515 bytes. Verification also completed in a non-root, offline, read-only
container limited to 2 GiB; actual maximum resident usage was 564,812 KiB.
The permanent [source-bound receipt](evidence/haos-41e58d3-image-inventory.json)
retains the original artifact/input hashes, scanner state, checked counts, fixed
runtime boundary flags and exact verifier source. It labels the original failed
workflow and subsequent local verification separately; it does not relabel CI as
successful or store image configuration, history or credentials. The bounded
build inspector validates the matching small index/process/probe receipt and
publishes only fixed counts/hashes/booleans. Contradictory source/image/scanner
claims or a providerless build claiming installed/model acceptance fail inspection.
This is real full-image inventory evidence, while the matching corrected CI,
ISO and installed acceptance remain separate required gates. No installed guest
success is attributed to the failed `41e58d3` workflow.

The corrected `e12a55d6d74c07d8f430947aad541efdf1371645` image now has a
successful actual [build job](https://github.com/BlueDragon4251/HAOS/actions/runs/38024496453/job/114132325410),
including scanner/verifier and UEFI ISO construction. Its 200,184-byte metadata
archive was independently downloaded and checked against GitHub's SHA-256;
the fixed source/image/scanner/index/UI receipts passed the bounded inspector.
The permanent [build receipt](evidence/haos-e12a55d-build-inventory.json) retains
80 installed/frozen Python versions, 1,210 RPM identities and 188 npm build
packages, document hashes/sizes and the actual offline scanner exit-zero/non-OOM
receipt without publishing image configuration or credentials. Full catalogs
remain in the separate image SBOM artifact. Installation and both guest boots
were still running when inspected; this successful build receipt does not accept
those guests, a real model turn or the complete release.

Catalogs and inventories improve release evidence; they do not prove exhaustive
identification of every vendored/embedded C/C++/Rust/Go/WASM component or complete
license/vulnerability review. The npm build graph and image catalog are distinct
documents, not a merged full dependency graph. Hermes model/gateway behavior,
signatures/provenance, reproducible base/builder inputs, installed acceptance,
Secure Boot and physical hardware remain independent release gates. No Stable
release is authorized by a successful catalog.
