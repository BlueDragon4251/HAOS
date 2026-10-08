# HAOS service and authority boundary

Herald remains the native Electron/React shell. The image installs the exact Hermes source from
`upstream/UPSTREAM.lock` under `/usr/lib/haos/hermes`, with its frozen dependency lock and an
image-owned Python. No Hermes core files are patched. The normal HAOS session attaches to
`haos-hermes.service`; missing credentials or a broken descriptor never cause an unrestricted
fallback child. Quitting or restarting Electron does not stop that service.

## Identities

| Identity | Authority | Persistent state |
| --- | --- | --- |
| Observer/owner session (`hermes` by default) | Native UI, mission submission and one-time tool responses; owner actions require sudo authentication | Herald preferences in its own home |
| `haos-agent` | Upstream Hermes and ordinary commands inside the restricted filesystem view; no wheel, login, owner API, controller socket or container socket | `/var/lib/haos-agent`, `/var/lib/haos-workspace` |
| `haos-control` | Queue, dispatch receipts, local API authenticated with Linux `SO_PEERCRED`; cannot grant volumes or run privileged commands | `/var/lib/haos-control/missions.db` |
| Root owner broker | Stable-volume resolution, mount preparation and offline recovery; no arbitrary command/path/options endpoint | `/etc/haos/volumes.json`, `/var/lib/haos-owner/audit.jsonl` |

The UI's existing bridge permissions are not this authority. The isolated agent is deliberately
not given the unrestricted Herald UI bridge or observer home: that bridge can execute commands
outside the agent namespace. A restricted native GUI execution broker still needs implementation
and adversarial testing before agent-driven host applications are enabled.

## Missions

SQLite uses WAL, FULL synchronization, schema versioning, transactions and a unique idempotency
key per authenticated actor. A persistent `agent-home` lock serializes shared-home work. A claim
is durable before session creation, and the dispatch marker is committed **before** `prompt.submit`.
Connection failures before that marker retry with bounded backoff. Failures or controller restarts
after it block execution and retain the lock. The controller never automatically repeats a prompt
whose admission is uncertain. Owner reconciliation requires both services to be stopped and an
inspection receipt. Deadline and cancellation interrupt Hermes and wait for a terminal event;
missing receipts block rather than invent an outcome.

The adapter uses the pinned `session.create`, `prompt.submit`, `session.interrupt`, server
`approval`/`clarify` requests and `message.complete` event. Tool events, usage and result text are
recorded from received Hermes frames. `completed` means an upstream successful **turn receipt**;
it does not independently certify the user's goal, artifact contents or external side effects.
Approvals permit only the offered `once`/`deny` choices. Sudo, secret and vault requests are rejected;
provider setup uses upstream's authenticated setup interfaces instead.

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

The runtime retains host networking for provider access. Isolation of privileged services exposed
over loopback TCP, per-mission network policy, desktop capture and gateway-to-controller identity
mapping remain unfinished. Do not deploy privileged unauthenticated loopback services alongside it.

## Verification status

Local checks on 2026-10-08: 19 HAOS unit/SQLite/wire-contract tests and 726 existing desktop tests
passed; desktop typecheck and production build passed. Service syntax was parsed with
`systemd-analyze verify`; the existing firstboot executable is absent from this development host.
These are not boot/installation evidence. The local sandbox rejects the additional Bubblewrap
namespace (`open /proc/8/ns/ns failed`); real kernel and Unix-socket probes are committed separately
and required in the HAOS CI workflow. No kernel isolation, complete image, ISO, QEMU installation,
live provider mission, backup restore or signed release has been certified here.
