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

## ADR-008: Platform abstraction in two places

Machine facts and actions used by the shell (installed apps, system stats, open/reveal) go through
`apps/os/electron/platform/HostPlatform`; agent-facing capabilities go through the plugin's
`HostAdapter`. Both have a `darwin` implementation and typed stubs for `win32`/`linux` so the
Windows and standalone-Linux futures have a place to land without touching call sites.
