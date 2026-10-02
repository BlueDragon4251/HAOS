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
- `herald-os-tailor` skill so Hermes can reconfigure Herald OS itself (Omarchy).
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
- Signed and notarized macOS builds; auto-update channel.

## Herald OS Linux

No custom kernel at any stage. See `docs/LINUX.md` and ADR-012.

**Stage 1 (done): the session.** Fedora Cloud image + cloud-init, `greetd` autologin, `cage`
compositor, Electron shell in kiosk mode, Linux `HostPlatform` and `HostAdapter`
(`ps`, `ss`, `nmcli`, `wpctl`, `gio`, `journalctl`, `plocate`, `.desktop` entries). Runs in a VM
on the Mac (QEMU or UTM).

**Stage 2: Hermes owns the capability layer.**
- Capability broker: a small privileged D-Bus service holding the permission tiers, issuing
  mission-scoped grants, implementing the `xdg-desktop-portal` interfaces, and owning the audit
  journal. Shell and bridge route every privileged call through it (no enforcement at first).
- Confine the shell and the runtime (bubblewrap/Flatpak-style sandbox, Landlock, seccomp).
- Own wlroots compositor: foreign app windows inside Hermes windows, secure approval prompts drawn
  outside the shell, output power management.
- `hermes serve` as a systemd user unit on a Unix socket with peer credentials.
- SELinux policy for the session.

**Stage 3: a distribution.** Image-based atomic updates, signed ISO for x86 laptops and mini PCs,
recovery partition, hardware enablement. Apple Silicon stays VM-only until Asahi covers the
current chips.
