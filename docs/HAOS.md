# HAOS implementation and evidence

Herald's complete history was imported into the private independent `BlueDragon4251/HAOS` repository. Baseline `3c891adcd1f5c3b6eeadf4d20472d10d9516a999` is pinned in `upstream/HERALD.lock`: 121 main commits, 133 unique imported commits, release tags and office branches. Licenses/notices/authorship remain intact.

The [complete requirements](requirements/HAOS-MASTER-PROMPT.md) are the delivery target, not implemented-feature claims.

| Component | Implementation |
| --- | --- |
| Independent Hermes | `linux/haos/haos-hermes.service`; pinned immutable runtime, Fedora Python 3.11, service account, systemd credential, mandatory Bubblewrap namespace |
| Durable missions | `controller.py`, `store.py`; SQLite WAL/FULL, idempotency, deadlines, bounded pre-dispatch retry, retained lock for ambiguity |
| Local API | Fixed Unix socket/methods, kernel peer UID, no owner endpoint |
| Storage authority | `policy.py`, `owner.py`; protected schema, stable identities, root mounts, system disk denial |
| Native UI | Managed attachment, real mission/event list, cancellation requests, once/deny approvals and clarification |
| Image/VM gates | `haos-image.yml`, `test-haos-iso.sh`, `haos_guest.py`; real ISO build and guarded disposable multi-disk acceptance harness |

Native host-command GUI bridge access is not exposed to the isolated agent. A safe GUI broker remains missing. Ordinary chat/gateways are not automatically durable HAOS missions.

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
