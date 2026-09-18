# Architecture Decision Records

Short records of the decisions that shape Hermes OS. Newest last.

## ADR-001: Consume upstream Hermes, do not fork it

Hermes OS runs against the user's installed Hermes runtime (`$HERMES_HOME/hermes-agent`), which
`hermes update` keeps current. The only upstream code compiled into the shell is
`apps/shared/src` (JSON-RPC client and generated contract), vendored as a pinned snapshot in
`upstream/` and refreshed by `scripts/sync-upstream.sh`. Rationale: the runtime moves fast
(facade-plus-siblings decomposition, ~39k tests); a fork would fall behind within weeks, and the
upstream wire contract is already stable and generated.

## ADR-002: New lean shell instead of lifting the Hermes Desktop renderer

Hermes Desktop's renderer is ~585k lines and its chat, session and store layers are coupled to a
multi-connection pane shell. Hermes OS needs a fullscreen environment with a different information
architecture, so it builds its own renderer on the same transport. Desktop is used as a reference
for patterns (backend ladder, ready handshake, terminal IPC, design tokens), not copied.

## ADR-003: Sessions use `source: "hermes_os"`

Upstream folds the `desktop_ui` toolset into sessions whose source is `desktop`. Those tools need
client handlers that only Hermes Desktop implements. Hermes OS declares its own source so the agent
never sees tools it cannot complete.

## ADR-004: The system bridge is an out-of-tree plugin executing on the backend host

The bridge registers tools with `ctx.register_tool(..., toolset="hermes_os")` and never touches
core files. In Alpha the backend always runs on the same Mac as the shell, so the tools execute
server-side behind a `HostAdapter` abstraction. Client-side execution (for remote backends) is
deferred until upstream exposes a generic plugin server-request hook; the adapter boundary keeps
that move mechanical.

## ADR-005: Permissions reuse the upstream approval gate

Rather than inventing a parallel confirmation channel, mutating and destructive bridge operations
call `tools.approval.request_tool_approval`. The request surfaces to the shell as the standard
`approval` server request (once / session / always / deny), so approvals for shell commands and
for system-bridge actions share one card, one allowlist and one audit path. Destructive actions
use a per-call `rule_key` so "always" cannot persist for them.

## ADR-006: Fullscreen, not kiosk

Hermes OS launches fullscreen and frameless but always allows leaving (`Cmd+Ctrl+F` toggles
fullscreen, `Cmd+Q` quits). Alpha runs on top of the user's macOS session and must never trap them.

## ADR-007: REST runs in Electron main; the renderer holds no credentials

The session token stays in the main process. The renderer receives a WebSocket URL for streaming
and a `rest(method, path, body)` capability for everything else. A compromised renderer cannot
mint arbitrary authenticated requests outside the exposed capability.

## ADR-009: Answer both request contracts (server requests and legacy events)

The pinned upstream snapshot delivers `approval` / `clarify` / `sudo` / `secret` as server-to-client
JSON-RPC requests. The runtime most users have installed today (0.21.0) still emits them as
`<kind>.request` events answered through `<kind>.respond` RPCs. Hermes OS folds the legacy shape
into the same `ServerRequest` object (`apps/os/src/lib/legacy-requests.ts`), so cards and stores
have one code path and an older runtime keeps working until `hermes update` moves it forward.
The fallback is narrow, named, and covered by unit tests, as upstream's compatibility rule asks.

## ADR-010: System tools stay directly callable

Upstream defers plugin and MCP tools behind its Tool Search bridge (`tool_search` /
`tool_describe` / `tool_call`) to protect the prompt budget. Deferred, the model reliably fell back
to `terminal` for tasks the bridge handles better (a `find` over three folders instead of a
Spotlight screenshot query). There is no per-plugin "keep direct" knob upstream, so bootstrap sets
`tools.tool_search.enabled: off` and Settings exposes the switch. Cost: ~5k prompt tokens for the
eight schemas, cache-stable across a conversation. Proposed upstream: let a plugin manifest declare
`direct_toolsets`, or extend `_DIRECT_SURFACE_TOOLSETS` with session-source-gated toolsets.

## ADR-011: Backend is spawned with HERMES_DESKTOP=1

Upstream keys three behaviours on this flag: the loopback token-auth exemption when a public
dashboard URL is configured, the in-process cron ticker (no gateway is running), and orphan
reaping of backends the app previously spawned. Hermes OS owns its backend exactly the way Hermes
Desktop does, so it sets the flag (plus `HERMES_OS=1` for its own consumers). Session platform is
still taken from `source: "hermes_os"`, never from this env var, in line with upstream's
"surface capability is a property of the session" rule.

## ADR-008: Platform abstraction in two places

Machine facts and actions used by the shell (installed apps, system stats, open/reveal) go through
`apps/os/electron/platform/HostPlatform`; agent-facing capabilities go through the plugin's
`HostAdapter`. Both have `darwin` and `linux` implementations and a typed stub for `win32`, so the
Windows future has a place to land without touching call sites.

## ADR-012: Hermes OS Linux Stage 1 is a session, not a distribution

The first Linux target boots a stock Fedora Cloud image into the Hermes OS shell as the only
session. Kernel, systemd, NetworkManager and packaging stay Fedora's; Hermes OS owns what the user
sees. This proves the experience before any security or packaging work. See `docs/LINUX.md`.

- **Fedora Cloud Base + cloud-init, not the interactive installer.** The seed ISO creates the user
  and runs `linux/provision.sh` unattended, so a VM is reproducible from two scripts and works in
  both QEMU (scriptable) and UTM (nicer window) from the same qcow2.
- **`cage` as the Stage 1 compositor.** A kiosk compositor gives the shell the whole output with no
  code of our own; foreign apps stack fullscreen on top. Window management between foreign apps
  needs our own wlroots compositor and is deferred to Stage 2 with the capability broker.
- **`greetd` autologin.** `default_session` runs the compositor as the `hermes` user on VT1 and
  respawns it when it exits; there is no greeter UI. Crash recovery for free.
- **Electron on Wayland via Ozone, kiosk mode gated by `HERMES_OS_KIOSK=1`.** The same shell binary
  runs windowed on macOS and as the session on Linux; `window.ts` branches on the env var, not the
  platform, so a Linux developer can still run it windowed under GNOME.
- **The backend stays shell-managed.** `hermes serve` is spawned by Electron exactly as on macOS.
  A systemd user unit would add a second lifecycle model before the broker (Stage 2) gives it a
  reason to exist.
- **SELinux permissive on the Stage 1 VM.** greetd and cage have no tailored policy; enforcing
  mode blocks the session on Fedora. Writing policy is part of Stage 2's sandboxing work.
- **Repo copied into the VM, not used in place.** Native modules (`node-pty`, Electron) must be
  installed on Linux; rsync over SSH (`linux/dev/push.sh`) or from the VirtioFS share
  (`hermes-os-sync`) keeps one source of truth on the Mac.
