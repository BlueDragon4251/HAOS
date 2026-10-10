# HAOS implementation and evidence

Herald's complete history was imported into the independent `BlueDragon4251/HAOS` repository, which is now public. Baseline `3c891adcd1f5c3b6eeadf4d20472d10d9516a999` is pinned in `upstream/HERALD.lock`: 121 main commits, 133 unique imported commits, release tags and office branches. Licenses/notices/authorship remain intact.

The [complete requirements](requirements/HAOS-MASTER-PROMPT.md) are the delivery target, not implemented-feature claims.

## Current acceptance status (2026-10-10)

The [mission-scoped GUI broker](GUI-CAPABILITIES.md) now creates real native local
browser windows for the active Hermes mission, with separate kernel-authenticated
agent ingress, targeted renderer input/capture and durable no-replay receipts.
Local verification: **321 ordinary HAOS tests**, **three real Unix probes**,
**773 native tests**, TypeScript and production build pass. Actual Chromium
checks fill two fields, read their actual DOM values, mask password/file fields,
capture changed pixels and verify both renderer sandbox states plus
network/chooser/clipboard/foreign-window denials. The pinned Hermes
registry exposes the real tool through its terminal/deferred catalog. These are
component receipts. The actual native/controller Unix pipeline also passes input,
capture, denied methods, lost acknowledgement and controller process restart;
the interrupted fixture mission is blocked without replay. A real private Weston
14.0.2 virtual Wayland session passes both gates and records actual mission
toplevel/surface protocol. It uses an explicit providerless fixture, with no
installed niri or hardware claim. General CI, services and Arch packaging passed
at `9815847` and `71cc361`; their new installer runs remain pending. Installed
Wayland/model-driven acceptance remains required. Arbitrary host apps, online
browsing and complete GUI autonomy are still open.

Owner-configured encrypted local daily/weekly scheduling now reuses Restic and
retention, defers active execution and durably blocks uncertain modifying attempts.
**28 root-authority/real Restic tests** pass in a disposable offline container,
including seven new scheduler cases and existing corrupt-data/staged restore gates.
The real PAM/sudo owner probe passes after selecting a disposable password through
the unchanged production quality check. A prior PR run rejected a random fixture
password; this is retained as failed evidence. The installed QEMU gate now requires
the actual scheduled service/snapshot restore; matching new receipts are pending.
Always-running execution defers scheduling until owner maintenance; live coherent
snapshots and complete system recovery remain open.

Three newer installed-image runs are now verified against their exact source,
GitHub archive digest and matching actual serial/saved receipts:

- `fed663588608791ba1acfe310cd53e0bdbb6d441`: [image/installation/both boots](https://github.com/BlueDragon4251/HAOS/actions/runs/37982281962), [digest/guest-output verification](https://github.com/BlueDragon4251/HAOS/actions/runs/37995834544). Artifact `11645093765`, ZIP SHA256 `42a900b8030012059ecadf01f321039303ee12ec8f1dd69d0297d3b97e6b1026`; boot 1 `1778d86bb0aaa54c273bbca27ec0c0e6dfd7498dd42ba80ad2758749980287b7`, boot 2 `64b341a4990b9e11bd87aaf93626c35c7eb1654efc47264c2cab57dcd61fb0e8`.
- `e6a63051acd4d4132bf4ee733641f5cf7936ce8b`: [image/installation/both boots](https://github.com/BlueDragon4251/HAOS/actions/runs/37984772853), [digest/guest-output verification](https://github.com/BlueDragon4251/HAOS/actions/runs/37995837850). Artifact `11646666149`, ZIP SHA256 `14e40ceb942a5d064cc14e4e2c1076946829452312d45543c3bf49558c89181c`; boot 1 `1778d86bb0aaa54c273bbca27ec0c0e6dfd7498dd42ba80ad2758749980287b7`, boot 2 `85c11a25739f3634d8a7a2c20d1411a2d4adb92f13a6a912ed2a76e1fce5987f`.
- `4bd2728469c91104a1fe5db9209dc6592414e167`: [image/installation/both boots](https://github.com/BlueDragon4251/HAOS/actions/runs/37986821163), [digest/guest-output verification](https://github.com/BlueDragon4251/HAOS/actions/runs/37995840704). Artifact `11645484613`, ZIP SHA256 `b459548f0a97a48b838edddc8e0cbe5d8086a29bc860d9679af51bd667bd5c07`; boot 1 `1778d86bb0aaa54c273bbca27ec0c0e6dfd7498dd42ba80ad2758749980287b7`, boot 2 `b7b7499487e5abba20c111afa2b16e4336c3580a5ea2183c61450572e075a7a3`.

All three prove the installed foreign-owner write/rename/delete boundary, read-only/
blocked/device/mount isolation, owner/PAM and reboot/single-use recovery, persisted
missions and UI/backend restart separation. The first boot intentionally reports
post-reboot recovery flags as false; the second boot verifies them. These source-
specific foundation gates do **not** prove autonomous theme generation, the newer
observer gate, live models/gateways, full-system restore or complete release readiness.

The [dashboard observer gate](DASHBOARD-ACCESS.md) now enforces an explicit HTTP/
WebSocket read scope on the real pinned Hermes app. Root boot migration replaces
the former full observer-readable token; the controller receives its private
credential via systemd and native version-2 attach uses only the separate UI
capability. Raw config/OAuth/terminal/turn/session changes and server-request
answers are denied before upstream dispatch. Local **211 ordinary HAOS tests**,
**six actual UID/file migration probes**, native descriptor tests, both TypeScript
checks and production bundling pass. A real pinned providerless Hermes process
passes authenticated reads, HTTP/RPC denials, preserved actual controller session
creation and process-log credential checks. Image build and both guest boots now
require additional real boundary assertions; matching installed results remain
required. Graphical owner setup and full GUI/plugin authorization remain open.

The QEMU phase runner now reports its own child PID, CPU/RSS, serial-file size/age,
output filesystem space and deadline every 30 seconds without exposing command
arguments or serial content. Timeout terminates only its new process group and
remains failure; guest output, I/O failures and timeouts never trigger replay.
Local harness/privacy verification passes **38 cases**; three actual diskless
QEMU probes pass in a non-root, network-disabled container, including live TCG
metrics and timeout termination. These are process/acceleration probes, not an
installed guest receipt. Evidence inspection now selects a nonempty available
completed image run or one explicitly requested numeric ID, and rejects foreign
workflow/event/branch provenance before downloading source-bound guest archives.

The new [image SBOM gate](SBOM.md) catalogs the actual OCI image with a digest-pinned
offline scanner, preserves/normalizes the pinned npm build graph, and requires
exact source/image identity plus all frozen/installed Python and RPM epoch/version/
architecture entries. The index hashes the documents and is embedded in the build
manifest. Local **9 negative contract cases** and actual Docker/OCI catalog probes
passed on a disposable Fedora metadata fixture (147 actual RPM records, 80 actual
installed Python metadata directories), with the separate actual 188-package npm
graph. This is no actual HAOS-image/execution claim; matching CI remains required.
Local ordinary HAOS verification now passes **184 cases**. Complete embedded-component
coverage, license/vulnerability review, signing/provenance and reproducibility
remain independent release requirements.

At `aeac4ad14b935ccb4a9e63e61f4b2b07743bab21`, general CI, both service runs,
dependency verification and Arch packaging passed. The actual
[image run](https://github.com/BlueDragon4251/HAOS/actions/runs/37988845635)
built the Fedora image but failed its new catalog step; ISO construction and
installation did not run. The scanner failure must be resolved before claiming
HAOS-image SBOM or newer installed acceptance.

The scanner correction uses a real OCI layout and private disk-backed scratch,
initially retaining its 3 GiB cap and all catalog/inventory gates. A large disposable image
reproduces actual archive-reader OOM at 1 GiB; its OCI-directory scan passes under
the same limit and verifies all fixture inventories. Actual scanner exit/OOM
state is now captured before cleanup; matching HAOS-image results remain required.

The actual `bba8f3b` image still exceeded 3 GiB: its retained process receipt
proves an OOM kill, and ISO/installation were skipped. The scanner now has a
bounded 5 GiB build allocation, 1536 MiB Go soft limit, one worker and aggregate
resource samples. All catalogers/inventory assertions remain required; neither
the large local fixture nor a successful image build accepts the full-image SBOM.

The Arch job at `f6640c0` failed during container initialization with Docker Hub's
anonymous pull limit, before running packaging checks. Its input now uses Arch's
[documented official GHCR publication](https://github.com/archlinux/archlinux-docker)
at digest `sha256:ed261ac99d13e9636940e88df26ccd22b0d8d1c2139699870f0427c765352689`.
The actual image pulled and reported Arch build `20261009.0.609227`, base-devel
and its packaged keyring; package signatures, build/lint/install/CLI tests remain
unchanged. The matching [Arch packaging run](https://github.com/BlueDragon4251/HAOS/actions/runs/37991916114)
passed all existing package/signature/build/install checks. Rolling package inputs
are not yet reproducible release pins.

Owner [backup retention and recovery](RECOVERY.md) now offer an exact snapshot
inventory and explicit scoped retention, previewed by default. Full encrypted data
is checked before/after actual deletion/prune, and the final inventory must match
the structured receipt. Real Restic 0.18.0 probes preserve another tag/source group,
recover retained data, reject corrupted encrypted packs, and restore intentionally
damaged configuration/mission/theme fixtures into staging with actual SQLite
integrity/event/cancellation verification. Local **21 backup unit/real integration**,
**175 ordinary** and **33 harness/privacy** cases pass. New matching CI is required.
No whole-system/off-host/scheduled recovery or automatic live-state replacement
is claimed.

At `4bd2728469c91104a1fe5db9209dc6592414e167`, both actual
[push services](https://github.com/BlueDragon4251/HAOS/actions/runs/37986821269)/
[PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37986826502) and
[general CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37986826164) passed.
The downloaded complete push-run log archive confirms Restic **0.16.4** and all
four actual encrypted retention/deleted-project/damaged-state/corrupt-pack probes
passed in 29.97 seconds. No root fixture or security check was removed.

Complete [theme revisions](THEME-SDK.md) now preserve previous manifests/assets,
publish a fully written checksum-verified bundle before switching its index and
expose explicit version selection in native Appearance and the Linux CLI. Real
filesystem/restart/corruption/failure and native-to-Linux contract tests pass locally.
An isolated Chromium preview now renders production CSS, captures a real screenshot,
checks the actual composed text/control contrast and wallpaper decoding, and rejects
unusable new saved revisions before changing the session/prefs. Five actual local
renderer cases pass, including zero requests to a real network canary and corrupt
raster rejection. Linux CI now requires this probe and retains only fixture PNGs
and a source-bound receipt. Matching CI remains required; this is a representative
preview, not whole-shell/compositor or autonomous model acceptance. Agent generation,
whole-session activation and independent automatic crash rollback remain open.

At `e6a63051acd4d4132bf4ee733641f5cf7936ce8b`, actual
[Linux/macOS CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37984778123)
and both [push](https://github.com/BlueDragon4251/HAOS/actions/runs/37984772780)/
[PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37984778110) passed.
The actual Linux renderer step/upload passed at PR merge source
`fa30ace784851a3b9e5c8eee7511189cb3738dd6`; fixture artifact `11641984766` has GitHub
ZIP digest `d021eb10b17be5ab115c226f97bf2ee3c8a1ef81c5b89901009ab3d09acade2d`.
The cloud's download is blocked at `productionresultssa2.blob.core.windows.net`,
so those remote ZIP bytes were not locally verified. All five same production
renderer cases also passed locally at the clean exact branch commit, recording
`work_tree_dirty: false`. The saved onboarding draft adds the observed Actions
hosts and tested headless-render instructions; publishing it remains a user setting.

At `405cdcc`, [push services](https://github.com/BlueDragon4251/HAOS/actions/runs/37981424478),
[PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37981432542) and
[general CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37981432631) passed.
Local verification is **752 desktop tests**, both TypeScript checks, production
bundling and **313 bridge/Linux tests with one existing skip**. Ten new revision
and consumer cases use actual isolated files; the loader/config rendering test
is explicitly distinct from graphical/model acceptance.

Installed provider images `e954dd3` / `720c08c` built but failed their first guest
boot at controller startup. [Bounded evidence inspection](https://github.com/BlueDragon4251/HAOS/actions/runs/37963970719)
verified their exact ZIP digests and exposed `PermissionError: untrusted provider
service credential`. systemd 259.9 gives root-owned 0400 credentials a named
service-UID read ACL; its mask appears as mode 0440 even though the owning group
has no access. The loader now validates actual effective ACL permissions, rejecting
ordinary group-readable files, foreign users, writable service grants, symlinks,
hardlinks and oversized payloads. Four actual UID/ACL credential probes and **206
ordinary/wire/harness/privacy cases** pass locally. The production-hardening
systemd probe now invokes this loader on its real delivered credential. Matching
runner/Fedora installed results remain required; no failed ISO is marked accepted.

At `edbf8dc`, the actual ext4/XFS/Btrfs ACL gates passed on both service runs,
including all four credential ACL cases. The subsequent transient-systemd probe
failed to import `haos`: `ProtectHome` correctly hides the runner's checkout.
The fixture now stages the unchanged production loader/ACL modules under its
private `/run` directory before launching the hardened service. No production
restriction or assertion is relaxed. Local **175 ordinary** and **30
guest/harness/privacy** tests pass; the actual runner gate must pass separately.

Both actual `de2b989` [push services](https://github.com/BlueDragon4251/HAOS/actions/runs/37966221954)
and [PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37966227906)
passed the delivered-credential and all ext4/XFS/Btrfs gates (PR merge source
`fd4f1e10bb56bc2c443fc3c8021e86ec536f65af`). General CI and packaging passed.
Its [installed gate](https://github.com/BlueDragon4251/HAOS/actions/runs/37966222034)
built/installed and passed the initial runtime health wait, but failed inside
the first new foreign-owner sandbox probe. Guest ZIP `11639610761` was downloaded
and verified against SHA256
`792714eabac652945661af924a28f5739fa81ab775fb4b24ec5c41c20b16c6da`.
It has no completed boot receipt; captured child stderr was lost from the original
exception. New errors retain bounded, redacted stderr and never dump the command
or stdout. The fixture also fixes an independent namespace-contract error: exact
host UID 65533 is verified before launch, whereas inside Bubblewrap an unmapped
owner is checked as distinct from the service UID. Both checks remain required;
the real kernel probe separately checks the root-owned interpreter is unmapped.
Local **175 ordinary and 31 harness/privacy** cases pass. New actual namespace
and installed gates must confirm the corrected probe; other guest failures remain
possible and no complete `de2b989` installed acceptance is claimed.

The new embedded kernel program initially failed indentation in both `41b97fe`
service runs. `fed663588608791ba1acfe310cd53e0bdbb6d441` corrects it and adds tests
that compile both actual extracted `python -c` programs. Local **33 harness/privacy**
cases pass. Both [push services](https://github.com/BlueDragon4251/HAOS/actions/runs/37982281888)
and [PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37982288085),
[general CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37982288072) and Arch
passed at that source. These actual kernel gates confirm the host interpreter's
foreign UID becomes unmapped inside the single-UID namespace. Matching installed
foreign-owner read/write/delete and both boot receipts remain required.

Owner/recovery image `d8f95c8` passed both installed boots. Evidence inspection
verified guest ZIP `11630797221` / SHA256
`23f50479f3b370d17385aa5b03e216896fcb6c6062b492a7640bd1c8fb40de74`
and checked saved receipts against actual serial output. Receipt SHA256 values are
`1710552a4539cee6bcc09fdd44e4afa4749547dc0c42dedde81be869350305ce`
and `73e1de272f94862bb98f2cd669cafcee7e265c191cd0fb304b1de336a552979e`.
Checks attest real console enrollment/PAM, denied wrong/cached/arbitrary-root/Python
override authentication, single-use recovery codes, password reset after reboot
and denied code replay. This does not certify graphical locking, later provider
or ACL changes, external models/gateways or full production recovery.

[System health](SYSTEM-HEALTH.md) now exposes real kernel/filesystem/service metrics
in the native workspace. An independent controller sampler pauses new dispatch on
stale/unknown required measurements or critical space/memory/temperature pressure,
without replaying jobs or modifying owner policy. Local ordinary/wire/harness tests
and native TypeScript/production bundling passed. Matching service/installed results
remain required; no repair or per-mission resource/cost accounting is claimed.

[Volume permission delegation](VOLUME-ACCESS.md) now uses root-broker POSIX ACLs
and private generation-aware permission journals on ext4/XFS/Btrfs. Read-only
mount publication, safe rollback/unmount and ownership-free filesystem masks are
integrated with the existing mount authority. Ordinary/harness checks pass; cloud
scratch ACL/handle support is insufficient for the new full kernel probe. At
`672ff3a`, both [push services](https://github.com/BlueDragon4251/HAOS/actions/runs/37960339846)
and [PR services](https://github.com/BlueDragon4251/HAOS/actions/runs/37960347710)
passed, including the guarded actual ext4/XFS/Btrfs ACL disk step. [General CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37960347573)
also passed. Results were read from the job/step API; full logs are blocked on the
separate cloud host `productionresultssa11.blob.core.windows.net`. The follow-up
emits source-bound per-filesystem GitHub Checks receipts. The matching foreign-owner
QEMU image gate remains required; earlier chowned fixtures do not accept full access.

The [native conversation](NATIVE-MISSIONS.md) now routes managed text and existing
voice-transcript callers into the durable controller and opens the Hermes workspace
at startup. Lost replies retain opaque request metadata; reload performs peer-scoped
lookup without resubmission. Local verification passes **742 desktop tests**, both
TypeScript checks and production bundling. SQLite/reopened-store and actual Unix
peer tests cover admission lookup. Real model turns, GUI control and complete
voice-response playback remain separate open gates.

Ongoing development after `b809009` preserves the installed foundation. Credential-redaction
commit `52c1c3c` passed [services](https://github.com/BlueDragon4251/HAOS/actions/runs/37943091005),
[general CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37943090859) and
[Arch packaging](https://github.com/BlueDragon4251/HAOS/actions/runs/37943090895). Its separate
new image/guest gate is not inferred from those results.

Owner-onboarding/recovery commits `5fe8dfb` / `d8f95c8` add the independent tty2
console, private hashed single-use recovery codes, initial-owner locking and a
mandatory owner-readiness gate. A duplicate unit dependency line broke the
strict existing sandbox parser; `b668f40` preserves both requirements in one line.
The corrected [services](https://github.com/BlueDragon4251/HAOS/actions/runs/37950553668),
[CI](https://github.com/BlueDragon4251/HAOS/actions/runs/37950553671) and
[packaging](https://github.com/BlueDragon4251/HAOS/actions/runs/37950553642) passed.
Matching installed enrollment/password-recovery receipts remain pending.

The subsequent [provider integration](PROVIDER-SETUP.md) supplies a separate
credential UID, root-bound scoped model socket, protected owner Codex/API setup,
explicit local-model routes and immutable named-provider configuration. Local
checks pass **166 ordinary HAOS tests**, **27 guest/harness regressions**, and
**30 root fixture tests** (nine provider, seven recovery, seven gateway, seven
backup). Actual pinned Hermes resolver/Responses/OAuth API contracts passed
without network/model calls. New actual namespace, nftables, socket activation
and ISO gates are separately pending. No real model/Git/gateway mission is
claimed; the owner confirmed those credentials are not available.

The next gateway change supplies root-owned Telegram/Discord pairing and credential setup,
a separate transport UID/kernel-peer ingress, atomic replay-safe mission admission and durable
transport inbox/result outbox. Local evidence: **144 ordinary service tests**, **one real Unix
transport test**, **seven root-authority fixture tests** in an offline container, plus construction
and interface checks of both real pinned upstream adapters with 80 hash-verified dependencies.
No external gateway, model turn or new installed service result is claimed. Required first live
credentials are OpenAI Codex and Telegram, confirmed unavailable by the owner. Physical hardware
is also unavailable. See [gateway setup and limits](GATEWAY-MISSIONS.md); full product gates stay open.

At branch `2cebd11`, public GitHub runners passed both service runs, general CI and Arch packaging. Service checks include **119 ordinary HAOS tests, seven root backup cases, 22 QEMU/diagnostics regressions, four actual policy-access probes and nine further integration probes**. The real nftables, owner PAM/sudo and new production-hardening systemd sandbox boundaries passed. See the immutable runs in the final evidence section below.

The rebuilt `2cebd11` ISO passed actual runner byte verification, installed through UEFI and completed both real multi-disk/reboot guest receipts. The verified artifact proves isolated Hermes health, native UI process presence, observer and localhost network denial, fixture RW/RO/blocked-volume boundaries, local staged backup recovery, UI restart without backend PID change and cancelled offline queue/event persistence across reboot. DNS and procfs startup corrections are proven in the installed guest. This is the bounded foundation acceptance, not production release, graphical owner onboarding, general ACL access or a real provider/gateway mission.

The following evidence is chronological: earlier failures and pending statements belong to the source revision and date where they were recorded.

Queued reuse run [37949433898](https://github.com/BlueDragon4251/HAOS/actions/runs/37949433898)
selected a newer descendant image after its old harness commit. The existing ancestry
assertion correctly rejected it before QEMU; no guest receipt exists. Artifact selection
now checks ancestry before downloading, skips descendants and preserves the final
assertion and exact image/guest/harness identities. The selection rule was checked with
a real isolated two-commit Git repository; a new runner result remains required.

| Component | Implementation |
| --- | --- |
| Independent Hermes | `linux/haos/haos-hermes.service`; pinned immutable runtime, Fedora Python 3.11, service account, systemd credential, mandatory Bubblewrap namespace |
| Durable missions | `controller.py`, `store.py`; SQLite WAL/FULL, idempotency, deadlines, bounded pre-dispatch retry, retained lock for ambiguity |
| Local API | Fixed Unix socket/methods, kernel peer UID, no owner endpoint |
| Storage authority | `policy.py`, `owner.py`; stable identities, post-mount identity/flags/topology verification, stale-grant invalidation and rollback |
| Owner enrollment | Separate root-console account, required password quality, authenticated fixed CLI, rollback; real runner PAM/sudo probe passed at `2cebd11`, installed onboarding pending |
| Network guard | Required root nftables guard for agent socket UID; real runner IPv4/IPv6/connection boundaries and installed localhost denial passed at `2cebd11`; full egress policy pending |
| Owner recovery | `backup.py`, `haos-owner`; encrypted local Restic snapshots and verified staged restore with stopped execution units |
| Observer separation | `observer.py`, pre-session systemd guard; no inherited administrator groups, blank password or sudo authority |
| Native UI | Managed attachment, real mission/event list, cancellation requests, once/deny approvals and clarification |
| Image/VM gates | `haos-image.yml`, `test-haos-iso.sh`, `haos_guest.py`; real ISO build and guarded disposable multi-disk acceptance harness |

Native host-command GUI bridge access is not exposed to the isolated agent. The
bounded local browser capability now has real input/capture/inspection and durable
no-replay receipts; general host GUI control remains incomplete. Managed local
conversation and paired Telegram/Discord messages enter durable HAOS missions;
real provider/gateway acceptance and additional channels remain open.

## Recorded evidence

- Local HAOS: **20 passed**.
- Native mission UI (`227597b`): TypeScript and production build passed; **729 tests in 100 files passed**. Existing Linux/macOS CI passed.
- Remote `8499142a2be2ea988e640662e636e1fa6b8aa996`, HAOS run `37809413576`: **20 unit tests, 2 real socket/kernel probes and systemd syntax passed**.
- Kernel probes exercise permitted writes, denied read-only writes, hidden paths/devices, symlink escape, no effective capabilities, NoNewPrivileges, denied mounts and nested user namespaces.
- Initial image run `37807692793` failed before producing an ISO: uv could not find the requested managed interpreter. The next build tests the Fedora Python runtime correction.
- The corrected image run `37809406559` installed Fedora Python 3.11.16 and 81 frozen Hermes dependencies successfully, then failed while committing the image layer because the runner ran out of disk space. No ISO was produced. The workflow now reclaims unused runner SDKs and excludes irrelevant build context/cache files.
- The QEMU harness is syntax checked; no completed guest acceptance is claimed here. Require actual receipts/logs for the exact tested source commit.
- Subsequent theme import hardening rejects unsafe data/configuration/path values and symlinked/oversized manifests/assets. TypeScript and production build passed; **731 desktop tests in 101 files** and **108 Linux tests** passed locally. The combined bridge/Linux command reports **304 passed, 1 skipped, 9 AF_UNIX setup errors** in this restricted scratch environment. Real CI must cover those socket tests; they are not silently skipped.
- Later owner/credential hardening requires fully inactive execution units and transfers the backend secret by protected descriptor rather than public launcher arguments. At `0ea3b70d6189decb149530059d0168920ca7f807`, HAOS run `37815243954` passed **33 unit tests, two real socket/kernel probes and systemd syntax**. The kernel probe verifies the descriptor data arrives and is absent from process arguments. These results do not retroactively validate earlier credential handling.
- The Fedora bootc image and installer generation at `06fda70` completed successfully in run `37811624089`. Artifact upload was in progress when this evidence was recorded; installed-guest acceptance remains unproven. No ISO checksum or guest success is inferred from the completed build steps. This earlier image predates theme and credential hardening; require evidence for the exact source revision before acceptance.

`main` retains baseline, `dev` is integration target, `agent/haos-foundation` holds implementation. Draft PR #1 stays unmerged while critical gates are incomplete. See [limitations](KNOWN-LIMITATIONS.md) and [release gates](RELEASE.md).

## Continuation on 2026-10-08

- `92e0d97` adds actual per-phase QEMU acceleration probes and bounded TCG fallback; subsequent `d108d70` also handles KVM permissions changing between successful preflight and actual launch. An explicit initialization error with an empty guest serial log is required before retry; started guests, I/O errors and timeouts are not replayed. The latter correction responds to real failed acceptance run `37836993147`; it does not claim that the installation passed.
- `002b33a` puts the reviewed security dependencies into the image using a hash-pinned 80-package requirements overlay. Exact Hermes commit/pyproject/uv.lock inputs are checked before metadata changes; package consistency, installed versions and immutable provenance are recorded. Dependency run `37837492133` audited the committed requirements with no known vulnerabilities, generated Python CycloneDX evidence, installed the actual upstream Hermes CLI and passed the expired-JWT regression. This validates that dependency scope, not the entire OS or a completed new image.
- At `e7df237`, service run `37837743842` passed 40 HAOS unit tests, 10 runtime-selection unit tests, two socket/kernel probes and two actual diskless QEMU probes. Real KVM was denied on that runner; real multi-thread TCG initialized successfully and was selected. This is acceleration evidence, not installed-guest acceptance.
- After the launch-race correction, local HAOS/runtime-selection tests: **55 passed** (40 HAOS + 15 QEMU selection/launch tests); shell syntax and workflow YAML parse checks passed. No desktop changes were made in this continuation; older desktop evidence remains tied to its original source.
- New source image build `37838091836` and matching harness reuse run `37838091868` were started. Require their completed steps, checksums and both installed-guest receipts before marking installation/storage/reboot acceptance successful. Production owner authentication, general full-volume access, egress, safe GUI brokerage, gateways, autonomous themes, update/backup recovery and release signing remain incomplete.

At `d108d70`, PR service run `37838097614` subsequently passed 40 HAOS and 15 QEMU unit tests, two real socket/kernel probes, two real QEMU probes and systemd syntax. KVM was denied and TCG initialized successfully on this runner. Installed-guest receipts remain a distinct pending gate.

Owner recovery at `cea2117` adds fixed-scope encrypted snapshots and restores into new root-private directories, leaving live state untouched. At `88425fb`, [service run `37839452538`](https://github.com/BlueDragon4251/HAOS/actions/runs/37839452538) passed **62 unit tests** (40 ordinary HAOS, seven owner/root fixtures and 15 QEMU) and **five real integration probes** (two socket/kernel, two QEMU and one Restic). Restic 0.16.4 backed up a disposable project, recovered it after deletion with identical bytes and mode 0600, preserved neighboring/live state and denied a wrong password. Systemd syntax also passed. Root-owned fixture tests run explicitly as root rather than being skipped on ordinary CI accounts. This proves the local backup/restore implementation on that runner; installed-OS recovery, off-host storage/retention and whole-system/broken-update recovery remain open.

Observer separation at `9e0d4a3` removes inherited administrator groups, locks empty passwords and installs a validated UID-based sudo denial before the graphical session. First boot no longer creates a wheel account with an empty password. At `739bc62`, [service run `37842665703`](https://github.com/BlueDragon4251/HAOS/actions/runs/37842665703) passed **71 unit tests** (49 HAOS, seven owner/root, 15 QEMU), **six real integration probes** (the previous five plus an actual account/sudo probe) and systemd syntax. The fresh fixture really executed a NOPASSWD root command before hardening; afterward its administrator membership was absent, password locked, root command and sudoedit denied. Earlier CI failures at `9e0d4a3`/`3454270` were strict `visudo` rejecting an inherited runner-rule permission; fixture preparation at `739bc62` corrects that mode as root without weakening production validation. Automatic observer display and independent authenticated owner/lock/recovery enrollment remain unresolved.

Reused-image run `37838091868` was automatically cancelled by a later source push after 30 minutes of real TCG installation. Its verified artifact `11577498948` (ZIP SHA256 `08b86bf027e902c4a93cfa7717517be15d3a331c072083cb1dd1e676b15e4cd2`) records **image and guest probe `0ea3b70`**, harness `d108d70`, image run `37815239260`, and ISO SHA256 `3c173a95bcc891496016d8fdad890852d36f1601708c17cc4c471cb9ac0ed659`. Serial evidence shows Anaconda creating filesystems on the disposable `vda` and starting deployment of the included container; there are no completed installer/boot/reboot receipts. This is an older development image, not the new recovery/observer implementation. `739bc62` disables source-update cancellation of this long, image-specific reuse gate; timeouts still fail.

Image builds `002b33a` (run `37837492174`) and `d108d70` (run `37838091836`) subsequently completed/uploaded. The former's old launcher failed at actual KVM initialization; the latter includes the corrected launch guard and its guest gate is separate. New guest probes additionally exercise observer authority and actual installed owner backup recovery only when running their matching newer image. No runner or build success substitutes for those pending installed-OS receipts.

## Continuation on 2026-10-09

The completed evidence ZIP for reuse `37842665549`, artifact `11587661221`, was downloaded and verified against ZIP SHA256 `317fb92928b325dfda77625ef95cf4f8aa2faa7da9c6ea35ec77c8b4ebec2a05`. It records image/guest `9e0d4a3`, harness `739bc62`, and ISO SHA256 `08dc16ce7e09d66f23a51db214259e4c465158776c3fac410ccde3387cf96a34`. Contrary to the earlier timeout-only interpretation, the image **installed, booted through UEFI and completed firstboot**. Its guest health assertion failed around uptime 303 seconds; no storage/reboot acceptance receipts exist. The host then waited until the 30-minute timeout. The separate old installation artifact `11585970644` from image run `37842387497` was verified against ZIP SHA256 `ef15a54273e81de916c959c28d91b2b99ef0279cc4cf14e302310646834a3b4d` and contains an installer timeout, not success.

- `19e73a9`: guarded failure diagnostics capture bounded token-redacted service state/journals and power off only a root, DMI/marker-verified disposable guest. Service run [37878613150](https://github.com/BlueDragon4251/HAOS/actions/runs/37878613150) passed **78 units, six real probes and service syntax**. The reuse gate [37878610539](https://github.com/BlueDragon4251/HAOS/actions/runs/37878610539) subsequently failed with concrete service journals; see the correction below.
- `ab2e521`: the real frozen backend contract probe passed [dependency run 37879468377](https://github.com/BlueDragon4251/HAOS/actions/runs/37879468377), including actual process health/identity, missing/wrong-token denial and authenticated durable session creation, plus the scoped 80-package audit and JWT regression. No provider/model turn is claimed.
- `e8dd0aa`: post-mount stable identity, device number, filesystem, flags and current topology are checked before publishing grants; failure invalidates stale configuration and rolls back new mounts. [Service run 37879539364](https://github.com/BlueDragon4251/HAOS/actions/runs/37879539364) passed **87 units, six real probes and systemd syntax**; same-source general CI and Arch packaging also passed.
- Actual Fedora/ISO builds at `19e73a9` ([37878610546](https://github.com/BlueDragon4251/HAOS/actions/runs/37878610546)), `ab2e521` ([37879468233](https://github.com/BlueDragon4251/HAOS/actions/runs/37879468233)) and `e8dd0aa` ([37879537350](https://github.com/BlueDragon4251/HAOS/actions/runs/37879537350)) completed and uploaded. The latter two actually passed the backend contract inside the Fedora build. Latest `e8dd0aa` artifact `11594817313` has **ZIP** SHA256 `0f34b096a927b6c2c649f68d17ae3d7154691c02c671d3dd0685529c2efe19ff`; its ISO hash has not been read in this session. Subsequent installation jobs never started because of account billing, so all three workflows are overall `failure` despite successful builds.
- `325ac6a` and `5766295`: required socket-UID nftables guard, narrow backend/DNS/reply exceptions, trusted resolver ancestry and dedicated-table reload. Real IPv4/IPv6/old-connection/reply/other-user negative probes are committed. They have **not run**. Harness-only edits now reuse images; actual image/bridge/guest inputs still rebuild.
- `8f2957f`: separate strong-password owner account, fixed isolated Python launcher, per-call password-authenticated CLI only, and failed-provisioning revoke/lock/registry rollback. **133 local unit/regression tests**, actual hostile Python-startup/package denial, real `visudo` parsing and systemd/shell syntax passed. Actual new-account PAM/sudo and installed authentication probes remain pending. No graphical owner bootstrap/lock/recovery flow is claimed.

GitHub's annotation for newly scheduled jobs states: “The job was not started because recent account payments have failed or your spending limit needs to be increased.” At `325ac6a` no new CI/image job executed any step; this is not a code-test failure or green validation. Resolve the account's Billing & plans externally before rerunning required source-specific gates. Do not transfer earlier green tests to the newer guard/owner code. Current installed backend, real network/owner enforcement, provider/gateway/GUI autonomy, general ACL access, full recovery and signed release gates remain open.

## Installed startup diagnosis and correction

Reuse `37878610539` completed with failure at 04:16 UTC on 2026-10-09. Verified artifact `11594373852`, ZIP SHA256 `d15c550768450d66ad033b79682bf707a3ce896f714fa036cc4e9fbeda24a78f`, records image/guest `9e0d4a3`, diagnostics/harness `19e73a9`, and the same ISO hash above. The real firstboot/policy/observer/controller/greetd units succeeded. Hermes failed five times before exhausting its restart limit: `PermissionError` reading `/run/haos-policy/sandbox.json`. The marked guest shut down at uptime approximately 324 seconds and the host failed promptly, proving that the new diagnostic/poweroff path works; no storage/reboot receipts were produced.

Root cause: the policy unit's `UMask=0077` reduces requested `mkdir(0750)` directories to 0700; changing their group does not restore traversal. The broker now opens a verified root-owned, non-writable directory inode with no symlink following, then explicitly assigns its dedicated agent group and mode 0750. Compiled policy remains root-owned 0640, readable by the service and not writable by it. Symlinks, writable/foreign directories and pre-existing mounts are rejected before permission changes; mounted user data is not modified.

Local verification after the correction: **138 unit/regression tests passed**, including actual restrictive-umask/mode reproduction and rejection of unsafe runtime directories, with identity metadata simulated in the ordinary unit suite. The separate root filesystem probe recreates the original denied read, checks a real dropped UID can read the corrected policy but cannot write/unlink/create authority, and denies another group. It cannot run here: scratch maps only UID/GID 0 and rejects chown to an unmapped identity. It remains mandatory in CI; GitHub billing still blocks new jobs. Therefore the fix is implemented and locally regression-tested, but service-UID/installed-OS acceptance remains open. No VM gate is currently claimed successful.

## Portable test fixtures and local policy-access proof

On 2026-10-09, the cloud account's actual UID 1000 exposed five enrollment fixture failures and one network fixture failure. Enrollment fixtures now simulate only root identity/ownership metadata needed for disposable unit files; real modes, registry writes and rollback remain exercised. The network validation test supplies fixed resolver input. Three additional cases verify that foreign-owned, readable and symlinked enrollment locks never provision an owner. Production enrollment, policy and firewall code is unchanged.

- Non-root Python 3.11.16, pytest 9.0.2, websockets 15.0.1: **112 HAOS tests passed**, with the seven separately executed root-backup fixtures excluded, and **22 QEMU/diagnostics regression tests passed**.
- In a disposable offline Python 3.11 container: **119 HAOS tests and four real policy-access probes passed**. These overlap the ordinary suite; they are not 123 additional unique tests. The probes actually recreate the restrictive-umask failure, drop UID/GID, read the corrected root-owned policy, deny policy writes/unlinks/new files and deny the wrong group. Source/dependency copies are read-only; only temporary container files receive ownership changes. No host accounts, firewall or disks are modified. This is local filesystem evidence, not Fedora/systemd or installed-ISO acceptance.
- TypeScript passed; **731 desktop tests in 101 files passed**. Gitleaks v8.30.1 scanned the 147-commit history and working changes without findings before this commit.

The GitHub API is separately blocked by the cloud network policy; `api.github.com` has been added to the saved environment draft but is not yet active. Earlier billing-failed runs have not been treated as new executions. The new source must still receive its own service/image/installed-guest evidence; no completed ISO acceptance is claimed.

At `12e5213`, the new GitHub runners really started. [General CI 37889152799](https://github.com/BlueDragon4251/HAOS/actions/runs/37889152799) passed. [Service run 37889148833](https://github.com/BlueDragon4251/HAOS/actions/runs/37889148833) passed the ordinary/root unit suites, real policy-access, socket/kernel, QEMU, Restic and observer probes plus systemd syntax, then failed before installing nftables rules because the runner's actual DNS configuration did not satisfy root-ownership checks. Owner PAM was therefore skipped. The follow-up socket probe uses a separate real root-owned `/run` resolver fixture, retaining every IPv4/IPv6/old-connection/backend-reply/mutation assertion and all production trust checks. API and log retrieval now work after the required network domains were saved; draft publication is not inferred from that connectivity.

The local Docker kernel cannot execute the guard's fib/reject expressions: nftables returned `No such file or directory` for those kernel features. That failed local network probe is not a passing guard result and is distinct from the runner's DNS-fixture failure. Current source-specific network/PAM and installed-ISO results remain required.

## Public runner evidence at `c4e4fd3`

New jobs now execute normally after the repository became public. Historical billing failures above remain historical; they do not describe these runs.

- [PR service run `37889812944`](https://github.com/BlueDragon4251/HAOS/actions/runs/37889812944) passed **112 ordinary HAOS tests, seven root backup tests, four real policy-access probes, 22 QEMU/diagnostics regression tests and eight further real integration probes**, plus systemd syntax. The integration probes cover socket/kernel isolation, two diskless QEMU cases, actual Restic recovery, observer authority, nftables and owner PAM/sudo.
- The actual nftables receipt confirms IPv4/IPv6/mapped-address denial, existing agent connection revocation, permitted backend self-connections and reply traffic, denied firewall mutation and preserved other-UID traffic. Its protected resolver fixture retains the production root-ownership checks.
- The owner receipt confirms correct-password fixed CLI authentication, wrong-password and cached-authentication denial, denied arbitrary root commands and Python environment overrides, and no password in registry/audit. The first [push service attempt `37889809483`](https://github.com/BlueDragon4251/HAOS/actions/runs/37889809483) timed out in `useradd` after 30 seconds; the same source passed the PR run and the push rerun (attempt 2) on fresh runners. No production timeout or assertion was relaxed.
- Same-source [general CI `37889812952`](https://github.com/BlueDragon4251/HAOS/actions/runs/37889812952) and [Arch packaging `37889812908`](https://github.com/BlueDragon4251/HAOS/actions/runs/37889812908) passed. Local TypeScript, production build and 731 desktop tests also passed at this source; the bridge/Linux suite completed with **313 passed, one skipped**.

These are runner/fixture results. Installed service startup, multi-disk enforcement and both boot receipts still require the exact-source [image/installation run `37889809499`](https://github.com/BlueDragon4251/HAOS/actions/runs/37889809499). No provider turn, graphical owner onboarding or full release is inferred.

That run successfully built the native shell, Fedora bootc image and UEFI installer ISO. Its small metadata artifact `11597878643` was downloaded and verified against **ZIP** SHA256 `ad93ba9ed64d08859929147bdc75e3e57e423297dcf2a7e80eacb17523847d40`; the extracted files match the verified ZIP. The manifest records exact source `c4e4fd3d702fcaf743368cd1c30cfb11d09cfdff` and **ISO** SHA256 `5f6d3578a5c5bd415bc49ca0d05551bf26679e8bcaa072e7eb83a5ca028fb826`. The actual build-time backend receipt passed health, denied absent/wrong tokens, matched authenticated child identity and created a durable session. This providerless build probe does not prove installed systemd/namespace operation. The multi-gigabyte ISO bytes were not downloaded locally for this metadata check; the install runner separately verifies them before QEMU.

## Installed DNS compatibility gate

The installation job of `37889809499` completed with failure at 07:07 UTC. It verified the ISO bytes, installed successfully under genuine TCG after the guarded KVM launch fallback, and booted through UEFI/firstboot. Downloaded guest artifact `11600509015` was verified against ZIP SHA256 `c01058541f0a708d1c63483371a607591178dadb7dfff9a066c3e5a5cd3a8614`. Firstboot, policy, observer security, controller and greetd succeeded. The required network service refused system DNS ownership; Hermes was therefore never started, and health failed around guest uptime 328 seconds. The marked guest powered off promptly. Neither boot acceptance receipt exists.

Fedora includes systemd-resolved 259.9, whose supported runtime stub is service-owned. The follow-up recognizes only a root-controlled `/etc/resolv.conf` symlink resolving exactly to `/run/systemd/resolve/stub-resolv.conf`: it returns the existing fixed `127.0.0.53` DNS endpoint without reading or trusting any addresses in the service-owned file. Other resolver sources still require root-owned, non-writable ancestry. Agent-owned system links and writable root ancestry remain rejected. The prior generic error did not name the rejected inode; new errors and bounded metadata-only guest diagnostics identify it on future failures.

Local follow-up verification: **119 ordinary HAOS tests and 22 QEMU/diagnostics regression tests passed**. A separate offline root container passed **126 HAOS tests and four actual policy-access probes**, overlapping ordinary tests. Seven additional DNS cases exercise fixed-stub behavior, untrusted system links/ancestors and rejected service-owned upstream files. Fresh same-source runner and rebuilt-guest results remain required.

The owner `useradd` timeout recurred in both service runs at `1deff8a`. Targeted disposable diagnostic run [37907656476](https://github.com/BlueDragon4251/HAOS/actions/runs/37907656476) measured `/etc/skel` at **834912 KiB** and syscall metadata showed `useradd` copying Rust/LLVM binaries until the unchanged 30-second deadline. The fixture account was created and cleaned up; no password was set or traced. This explains why identical earlier source sometimes passed on a faster runner. CI now temporarily selects a fresh root-private skeleton under `/run` for the actual unmodified enrollment/PAM probe, restores the exact original `/etc/default/useradd` bytes and default output in `finally`, and removes only its fixture directory. Production commands, deadline and all authentication/authority assertions remain unchanged. The first setup attempt at `9865a52` used an unsupported `useradd --defaults --skel` combination and failed before the probe; it is corrected to the documented configuration file. The temporary tracing workflow was removed after diagnosis; fresh service results remain required.

## Current runner and rebuilt ISO evidence

At `c25172e99f257ce6a692bb0a0ae215db15d17502`, both [PR service `37908844313`](https://github.com/BlueDragon4251/HAOS/actions/runs/37908844313) and [push service `37908839388`](https://github.com/BlueDragon4251/HAOS/actions/runs/37908839388) passed **119 ordinary HAOS tests, seven root backup tests, 22 QEMU/diagnostics regressions, four actual policy-access probes and eight further real integration probes**, plus systemd syntax. Actual nftables and owner PAM/sudo receipts confirm every positive/negative boundary assertion; owner authentication completed in approximately two seconds with the corrected private skeleton. [General CI `37908844326`](https://github.com/BlueDragon4251/HAOS/actions/runs/37908844326) and [Arch packaging `37908844352`](https://github.com/BlueDragon4251/HAOS/actions/runs/37908844352) also passed.

The runtime/image source remains `1deff8a0a1f72e8e13131a6442f0b01bf9484d99`. All Git objects for Linux, apps, packages, plugins, scripts, guest tests, upstream pins, package manifests, container context exclusions and image workflow match `c25172e`; intervening changes only affect service-CI setup and documentation. [Image/install run `37906664147`](https://github.com/BlueDragon4251/HAOS/actions/runs/37906664147) successfully built/uploaded the new native shell, Fedora image and ISO. Metadata ZIP `11605492987` was verified against SHA256 `738c1ddb3431fea4504ac0f0251489b8c392f4c447d864f1d5de63b7a9017a01`, and its manifest records ISO SHA256 `a77b37299a08d3ac07a18a3bfe6250e58e305c081613ba73aa490885b8a7b03f`. Full build artifact `11606131711` has ZIP SHA256 `9f6423ae40c2c5ba0ffe356a9eff103839543e3dd4f852f9638b4985b56b2576`; this is distinct from its ISO hash. Actual ISO bytes passed the install runner's checksum check; installed-guest acceptance remains a separate running gate.

## Installed namespace startup correction

Run `37906664147` completed with failure at 09:52 UTC. The real TCG installation succeeded in approximately 35 minutes. Guest artifact `11608861003` was downloaded and verified against ZIP SHA256 `e8a9d3ed4013901e6ceb0f18543ac97922cf7d8895e3acf9e5b31c1f996fe8c8`. Its resolver metadata confirms the root-owned system symlink points to systemd-resolve's stub file. Firstboot, required nftables network service, policy, observer-security, controller and greetd succeeded. The DNS compatibility correction is therefore proven at installed service startup. Hermes repeatedly failed with `bwrap: Can't mount proc on /proc: Operation not permitted`; health timed out around guest uptime 294 seconds, and the marked guest powered off at approximately 304 seconds. No boot acceptance receipt exists; installed observer/network denial, storage and recovery assertions had not run yet.

Targeted disposable [diagnosis `37914619168`](https://github.com/BlueDragon4251/HAOS/actions/runs/37914619168), source `51cf8d5`, launched eight real transient systemd services using the production hardening settings. All four cases with `ProtectKernelTunables=yes` failed at the procfs mount; all four with it disabled succeeded, independently of `ProtectProc=invisible/default` and `PrivateDevices=yes/no`. Results were read directly through the GitHub Checks annotations API. Diagnostic artifact `11609530889` advertises ZIP SHA256 `45ad58dcc97ffaa086ab65656565bf9f51d0f42a64db79f9e719c5907c271089`, but its download is blocked by the cloud's separate network rules and that ZIP is not claimed verified.

The follow-up retains `ProtectProc=invisible`, private devices, empty capabilities, NoNewPrivileges and all namespace restrictions. It disables only systemd's conflicting pre-mask and explicitly remounts the sandbox's own PID-namespace `/proc` read-only; `/sys` remains absent. The real kernel probe now verifies read-only procfs/tunables and an actual harmless control write fails with EROFS, alongside all existing file, capability, mount and nested-userns denials. A separate transient-service probe reuses that full filesystem probe under the current unit's actual hardening options and systemd credential delivery, substituting only disposable state paths and the runner identity. The temporary diagnostic workflow is removed. Local **119 ordinary HAOS tests, 22 QEMU/diagnostics regressions**, unit syntax and workflow/probe parsing passed. New real service and rebuilt-ISO results are still required for this production change.

At `2cebd11c4c97afc9add4eba08767c3d03395fb52`, [PR services `37915395770`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915395770), [push services `37915386717`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915386717) and [general CI `37915395857`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915395857) completed successfully. Each service run now includes the new actual transient-systemd sandbox probe, which passed in approximately one second, plus all previous tests and integration gates. Results and step identities were read through the Actions API; full service logs are on a separately blocked cloud egress host and have not been read yet. New [image/install `37915386805`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915386805) is running; require its own ISO hash and both installed-guest receipts.

[Arch packaging `37915395766`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915395766) also completed successfully at `2cebd11`.

The saved cloud setup's exact bridge invocation was additionally verified at `2cebd11` using `/workspace/HAOS/.venv/bin/python` (Python 3.12.14): **313 passed, one skipped**. This complements the earlier Python 3.11 bridge verification and does not imply a model or installed-OS mission.

The `2cebd11` image build completed successfully and uploaded its native shell, Fedora image and UEFI ISO. Metadata artifact `11610066031` was downloaded and verified against ZIP SHA256 `27180265beab923106762e272fcd82f29c466461d25f66603bf46374b6e55232`. Its manifest and checksum file match exact source `2cebd11c4c97afc9add4eba08767c3d03395fb52` and ISO SHA256 `0dcea328c23f8067212dbaebf4d92f69514fbe990e91385e3972c70486e09183`. The build-time backend health/authentication/child identity/durable-session assertions passed. Actual ISO-byte verification and both installed guest receipts remain separate gates on the newly started install runner.

Install job `113777488746` passed actual ISO-byte verification and began its combined QEMU installation/multi-disk/reboot step at **10:29:35 UTC**. Full build artifact `11610911034` advertises ZIP SHA256 `c1fcada5b79c55b14d2afb2f51f0c7d2333b2ac67cebde081c01256c51b0d5eb` (3911077811 bytes); that archive was not downloaded locally and its hash is distinct from the ISO hash. Installed acceptance is pending.

## Completed installed foundation acceptance at `2cebd11`

[Image/install run `37915386805`](https://github.com/BlueDragon4251/HAOS/actions/runs/37915386805) and install job `113777488746` completed successfully at approximately **11:04 UTC**. Actual KVM initialization was denied before guest output, triggering the guarded real multi-thread TCG fallback. The installer powered down successfully after approximately 27 minutes; both installed boots then completed. Guest artifact `11612357305` was downloaded and verified against ZIP SHA256 `7bfbfa45f3956ce82312791cb3b575b6129769a0d9ac1bfa3515548efde3ce00`. Both `acceptance-1.json` and `acceptance-2.json` match the JSON emitted in their actual boot logs, and neither boot has a failure marker. Image and harness source are both `2cebd11c4c97afc9add4eba08767c3d03395fb52`; ISO SHA256 remains `0dcea328c23f8067212dbaebf4d92f69514fbe990e91385e3972c70486e09183`.

- First boot: actual Hermes health and native UI process presence; observer sudo/administrator/empty-password denial; installed service-UID localhost listener denial; encrypted owner CLI backup and staged deleted-fixture recovery with exact bytes/mode and live state untouched; real approved writes, read-only write denial, blocked/owner paths and raw devices hidden, denied symlink escape, mounts and nested user namespaces; UI restart preserving the backend PID.
- Second boot: backend healthy again; observer and localhost denials still enforced; the same cancelled offline mission and its event history survive reboot.

The data-volume test deliberately assigns ownership only to its serial/UUID-verified disposable fixture; this does not accept general ACL/idmapped access. Backup restores into staging and does not test whole-system/off-host or broken-update recovery. UI evidence is process presence and restart separation, not graphical task execution, owner bootstrap/locking or autonomous themes. The queue fixture is offline/cancelled and proves no provider/model/Git/gateway mission. Builds remain unsigned and the remaining production release gates stay open.
