# Roadmap

## Alpha 0.1 (macOS, Apple Silicon)

- Fullscreen Hermes-powered environment running on the user's Hermes install.
- Surfaces: Home, Chat, Agents, Tasks, Skills, Files, Apps, Terminal, System, Settings,
  Notifications, global command bar.
- System bridge plugin with permission tiers and audit log.

## Alpha 0.2

Borrowed from the field (see `LANDSCAPE.md` for the source of each):

- Crash and error capture handed to Hermes with a `diagnose-crash` skill (Omarchy).
- Whole-environment themes driven by Hermes skins; agent-authored themes (Omarchy).
- Agent Task Manager: per-session resources, tokens, approvals, stop (OpenNeo).
- Live "Hermes is acting" banner with Interrupt during GUI automation (SomaOS).
- `hermes-os-tailor` skill so Hermes can reconfigure Hermes OS itself (Omarchy).
- `system_shortcut` tool over macOS Shortcuts / App Intents (Apple).

Also planned:


- Client-side bridge execution for remote/cloud backends (needs a generic plugin server-request
  hook upstream; proposal to be opened against `tui_gateway/contracts/server_requests.py`).
- Projects: bind sessions to folders, open project workspaces from Home.
- Kanban board surface on `/api/plugins/kanban`.
- Voice input through the existing gateway voice methods.

## Beta

- Windows: `HostPlatform`/`HostAdapter` implementations (PowerShell, `Get-Process`, Everything or
  Windows Search for file search), NSIS installer.
- Linux desktop session: `HostAdapter` on `xdg-open`, `ps`, `ss`, `locate`/`fd`.
- Signed and notarized macOS builds; auto-update channel.

## Standalone Hermes OS (Linux-based)

Out of scope until the shell is proven on macOS and Windows. The plan is a minimal compositor
session (Wayland) that boots straight into the Hermes OS shell with the same renderer, the same
runtime, and a Linux `HostAdapter`. No custom kernel.
