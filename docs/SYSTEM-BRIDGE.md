# System Bridge

The system bridge is how Hermes acts on the computer. It is a Hermes plugin
(`plugins/hermes-os-bridge`) that registers a small toolset named `hermes_os`. Every capability is
an explicit tool with a typed schema, a permission tier, and an audit record. The model never gets
unrestricted machine access.

## Tools

| Tool | Tier | Purpose |
| --- | --- | --- |
| `system_info` | read | OS version, hardware, uptime, CPU load, memory, disks, battery |
| `system_processes` | read | Top processes by CPU or memory, find by name, find by listening port |
| `system_disk_usage` | read | Largest entries under a directory (bounded depth and time) |
| `system_find_files` | read | Spotlight (`mdfind`) search: name, kind, screenshots, date ranges, scope |
| `system_apps` | read | Installed applications and currently running applications |
| `system_open` | act | Open an app, URL, file or folder; reveal in Finder; open a path in an editor |
| `system_kill_process` | destructive | Terminate a process by pid or by listening port |
| `system_files` | mutate / destructive | Create folders, move, rename, trash (never `rm`); `dry_run` plans |

"Start my development environment" is a skill: it composes `system_open` with Hermes's existing
`terminal` tool rather than adding another core-shaped tool.

## Permission tiers

| Tier | Behaviour | Examples |
| --- | --- | --- |
| `read` | Runs immediately, audited | info, processes, disk usage, search |
| `act` | Runs immediately, audited, surfaced as a notification | open Safari, open a repo in VS Code |
| `mutate` | Requires confirmation; `session` and `always` are honoured | mkdir, move, rename |
| `destructive` | Always requires confirmation; per-call rule key so `always` cannot persist | kill process, trash files |

Confirmation goes through upstream's `tools.approval.request_tool_approval`, which the shell
renders as its approval card. `approvals.mode: off` and yolo mode are honoured exactly as they are
for shell commands, because it is the same gate.

## Protected paths

Operations that would read or modify these locations are refused before any approval prompt:
`~/.ssh`, `~/Library/Keychains`, `$HERMES_HOME/.env`, `/System`, `/usr`, `/bin`, `/sbin`,
`/private/etc`, `/Library`. The list is extended in the policy file.

## Policy file

`$HERMES_HOME/hermes-os/permissions.yaml`

```yaml
version: 1
tiers:
  read: allow          # allow | confirm | deny
  act: allow
  mutate: confirm
  destructive: confirm # cannot be set to allow
protected_paths:
  - ~/Documents/Taxes
```

## Audit log

Every tool invocation appends one JSON line to `$HERMES_HOME/hermes-os/audit.jsonl`:
`{ts, tool, tier, action, args, decision, ok, error}`. Arguments are truncated; no file contents are
logged.

## Platform abstraction

`bridge/host/base.py` defines `HostAdapter`. `darwin.py` implements it with `mdfind`, `open`,
`lsof`, `ps`, `osascript`, `system_profiler`, `vm_stat`. `windows.py` and `linux.py` raise
`HostNotSupported` with a clear message; they exist so the tool layer never branches on
`sys.platform`.
