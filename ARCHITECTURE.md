# HAOS architecture

The inherited native Wayland/niri/Electron shell remains the session interface. The independent systemd Hermes service is the execution boundary; closing the observer UI does not own its lifetime. The controller separately owns the durable mission journal. The root storage service and owner CLI own policy and mounts.

| Identity/component | Authority and contract |
| --- | --- |
| Observer UI | Managed descriptor/backend token; fixed mission IPC; no storage/root endpoint |
| haos-control | Peer-authenticated Unix socket; SQLite mission state; upstream loopback JSON-RPC |
| haos-agent | Immutable Hermes source/dependencies; writable private home/workspace and explicit data binds; no owner privileges |
| Root policy service | Stable device resolution, protected policy, global mounts and compiled grant list |
| Authenticated owner | Stop/start, policy changes and uncertain mission reconciliation through fixed CLI |

Mission state is journaled before dispatch. Crash ambiguity retains a resource lock; a retry cannot prove destructive work did not execute. Agent code and generated skills inherit only the filesystem namespace, not root or observer environment. The existing host-command GUI bridge is not exposed.

See [runtime](docs/HERMES-RUNTIME.md), [missions](docs/MISSIONS.md), [storage](docs/STORAGE-POLICY.md), [threat model](docs/THREAT-MODEL.md) and [known limitations](docs/KNOWN-LIMITATIONS.md). The [baseline inventory](docs/architecture/upstream-inventory.md) and existing [Herald architecture](docs/ARCHITECTURE.md) document inherited components. Gateway ingress, safe GUI broker, theme watchdog, owner setup and backup/update recovery still need completion.
