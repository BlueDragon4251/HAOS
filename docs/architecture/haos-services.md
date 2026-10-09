# HAOS service and authority boundary

Herald remains the native Electron/React shell. The image installs the exact Hermes source from
`upstream/UPSTREAM.lock` under `/usr/lib/haos/hermes`, with its frozen dependency lock and an
image-owned Python. No Hermes core files are patched. The normal HAOS session attaches to
`haos-hermes.service`; missing credentials or a broken descriptor never cause an unrestricted
fallback child. Quitting or restarting Electron does not stop that service.

## Identities

| Identity | Authority | Persistent state |
| --- | --- | --- |
| Observer session (`hermes` by default) | Native UI, mission submission and one-time tool responses; no owner/sudo authority | Herald preferences in its own home |
| Enrolled owner (separate new account) | Password-authenticated fixed recovery/policy CLI; no unrestricted sudo | Separate home; protected identity registry |
| `haos-agent` | Upstream Hermes and ordinary commands inside the restricted filesystem view; no wheel, login, owner API, controller socket or container socket | `/var/lib/haos-agent`, `/var/lib/haos-workspace` |
| `haos-control` | Queue, dispatch receipts, local API authenticated with Linux `SO_PEERCRED`; cannot grant volumes or run privileged commands | `/var/lib/haos-control/missions.db` |
| `haos-gateway` | Pinned messaging adapters, exact owner-paired senders and scoped mission ingress/outbox; no general control/owner API | Private transport inbox and credentials delivered by systemd |
| `haos-provider` | Fixed model API routes under owner allowlists; real provider/OAuth credentials kept outside agent/gateway namespaces | Private OAuth and bounded usage metadata; root-private API key store |
| Root owner broker | Stable-volume resolution, mount preparation and offline recovery; no arbitrary command/path/options endpoint | `/etc/haos/volumes.json`, `/var/lib/haos-owner/audit.jsonl` |

The UI's existing bridge permissions are not this authority. The isolated agent is deliberately
not given the unrestricted Herald UI bridge or observer home: that bridge can execute commands
outside the agent namespace. A restricted native GUI execution broker still needs implementation
and adversarial testing before agent-driven host applications are enabled.

The root network guard installs a dedicated agent socket-UID table with only CAP_NET_ADMIN and is required before Hermes. See [network policy](../NETWORK-POLICY.md) for actual kernel evidence and the bounded historical installed receipts; newer installed and complete egress acceptance remain required.

## Missions

SQLite uses WAL, FULL synchronization, schema versioning, transactions and a unique idempotency
key per authenticated actor. A persistent `agent-home` lock serializes shared-home work. A claim
is durable before session creation, and the dispatch marker is committed **before** `prompt.submit`.
Connection failures before that marker retry with bounded backoff. Failures or controller restarts
after it block execution and retain the lock. The controller never automatically repeats a prompt
whose admission is uncertain. Owner reconciliation requires both services to be stopped and an
inspection receipt. Deadline and cancellation interrupt Hermes and wait for a terminal event;
missing receipts block rather than invent an outcome.

The controller's separate [read-only health sampler](../SYSTEM-HEALTH.md) reports
actual kernel, filesystem and fixed-service measurements. New dispatch requires
fresh safe storage/memory/thermal measurements; pressure leaves saved jobs queued
without consuming attempts. No UI/model request can invoke repair or modify this
root-independent measurement surface. Existing in-flight ambiguity handling remains.

The adapter uses the pinned `session.create`, `prompt.submit`, `session.interrupt`, server
`approval`/`clarify` requests and `message.complete` event. Tool events, usage and result text are
recorded from received Hermes frames. `completed` means an upstream successful **turn receipt**;
it does not independently certify the user's goal, artifact contents or external side effects.
Approvals permit only the offered `once`/`deny` choices. Sudo, secret and vault requests are rejected;
provider setup uses upstream's authenticated setup interfaces instead.

HAOS now provisions providers through the authenticated owner CLI and a separate
[credential-isolated model broker](../PROVIDER-SETUP.md). The unmodified pinned
Hermes runtime receives an immutable named custom provider and only a scoped
loopback capability. Codex's real OAuth resolver/refresh runs in the separate
provider identity. Neither terminal tools nor gateway events can grant models,
change provider endpoints or read the real provider credential store. External
model/gateway acceptance still requires credentials and real receipts.

The native shell now uses a separate [observer capability](../DASHBOARD-ACCESS.md).
An image-owned middleware on the actual pinned upstream ASGI app permits only
explicit read scopes; raw configuration/OAuth, turns/session changes, terminals,
browser registration and server-request answers are denied independently of the
UI. The root boot migration rotates the former observer-readable backend token;
the private controller receives its independent credential via systemd. Native
version-2 attach refuses the former private-token descriptor. Real local pinned
HTTP/WS and UID migration probes pass; matching installed acceptance remains
required. Native graphical owner flows and full GUI/plugin capability brokerage
are still missing; legacy protected settings must use authenticated owner setup.

## Filesystem enforcement

The core runs as `haos-agent`, with no ambient capabilities, no new privileges, private devices,
and Bubblewrap user/PID/mount/IPC namespaces. Its root is assembled from immutable `/usr`, a fresh
`/proc`, synthetic `/dev`, private temporary storage, its own state/workspace, selected network and
certificate configuration, and explicitly granted data mounts. Host `/etc`, `/run`, `/var`, home
folders, `/sys`, raw devices and container sockets are not bound. Nested user namespaces are
disabled. Environment inheritance is cleared; no Electron parent PID or owner credentials enter
the runtime.

Root-only policy accepts UUID/PARTUUID identities and four modes. Unknown identities, duplicate
UUIDs, unsupported/encrypted filesystems and disks containing system/owner mounts fail closed.
Granted filesystems mount with `nodev,nosuid,noexec`; read-only grants also use a read-only bind in
the agent view. All other volumes default to absent. Encrypted data must first be unlocked through
owner recovery; automatic LUKS secret acquisition is not implemented. Policy changes require the
services to be stopped, so a running process cannot retain a revoked bind.

The runtime retains host networking for provider access. A required [socket-UID guard](../NETWORK-POLICY.md) restricts local/private destinations with narrow backend/provider/DNS/reply exceptions. Kernel CI and bounded historical installed receipts are linked there. Root-paired Telegram/Discord identity mapping and persistent gateway ingress exist; real credentialed round trips, additional adapters, AF_UNIX abstract services, per-mission network policy and desktop capture remain unfinished. Do not deploy privileged unauthenticated loopback services alongside it.

## Verification status

Current source-specific component and installed evidence is maintained in
[HAOS.md](../HAOS.md) and [Issue #2](https://github.com/BlueDragon4251/HAOS/issues/2).
The following initial verification entries are historical and must not replace
the newer exact-commit results or imply full release acceptance.

Local checks on 2026-10-08: 19 HAOS unit/SQLite/wire-contract tests and 726 existing desktop tests
passed; desktop typecheck and production build passed. Service syntax was parsed with
`systemd-analyze verify`; the existing firstboot executable is absent from this development host.
These are not boot/installation evidence. The local sandbox rejects the additional Bubblewrap
namespace (`open /proc/8/ns/ns failed`); real kernel and Unix-socket probes are committed separately
and required in the HAOS CI workflow. No kernel isolation, complete image, ISO, QEMU installation,
live provider mission, backup restore or signed release has been certified here.

The subsequent native UI integration submits HAOS missions to the controller, displays its seven
states and persisted event cursor, routes one-time answers and cancellation through the existing
OS command registry, and preserves request keys on transport retries. Local verification now
passes 20 HAOS tests, 729 desktop tests, typecheck and build. The existing CI (Linux/macOS desktop,
bridge, script parsing and secret scan) passed at `f6127a5`. The first kernel probe failed because
Bubblewrap requires explicit `--unshare-user` with `--disable-userns`; this has been corrected and
must pass the next CI run. The actual Unix-socket roundtrip already passed in that run.
