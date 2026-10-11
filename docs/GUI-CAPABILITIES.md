# Mission GUI capability

The image-owned `haos_gui` tool uses the pinned Hermes public tool registry and
its real session ContextVars. The separate `/run/haos-gui-agent/gui.sock` listener
authenticates the kernel agent UID. It accepts only `gui.submit`/`gui.result` for
the controller’s running, dispatched, non-cancelled, unexpired mission.
A supplied mission/owner identity does not grant authority. The old host bridge,
niri/Wayland socket, owner paths and general control socket remain outside the
agent’s filesystem view. The tool is discoverable through Hermes’ terminal
catalog, including its normal deferred tool-search mechanism.

Herald’s main process polls a different authenticated control surface and creates
real native Chromium windows. Its boundary independently validates actions and
the window’s mission. Private random window UUIDs prevent compositor IDs, titles,
other missions or owner windows from authorizing input or capture.

Actions: `open` (static local HTML, 32 KiB maximum), `state`, `focus`, `close`,
`click`, `scroll`, `type`, `key`, `capture`, `inspect`, `read`. Inspection reads actual input/textarea
values through a fixed DOM snapshot on the mission document. `read` returns at most 8192 UTF-8 bytes of actual layout text in the current document viewport, with explicit truncation. Hidden/zero-opacity content and form values are excluded, including ancestor styles. This content is untrusted data, never authority. `scroll` sends a fixed renderer-targeted wheel event with bounded pixel deltas, without seat input. Use subsequent read/capture receipts to verify navigation. Password/file fields
are masked independently; long values report truncation. The owner renderer and
caller-supplied debugger/JavaScript/selector APIs are inaccessible. Inspection
bodies expire like captures; only their digest/count persist in the GUI ledger.
Up to four separate 800×600 windows per mission, each with its own disposable Chromium partition; the first 48
pixels contain a fixed mission banner outside caller content. `focus` raises the
window without granting seat keyboard focus. Input uses the isolated document
renderer’s fixed CDP commands and actual DOM hit-tests, not caller JavaScript.
Capture targets only that window. The tool saves actual JPEGs to private random
files in `/workspace/.haos-captures`, usable by vision tools.

Each window has a disposable partition, Chromium sandbox, no preload/Node/caller
JavaScript and an opaque iframe without sandbox exceptions. Resource requests,
network/file/custom-scheme navigation, workers, form submission, nested application
surfaces, popups, downloads and permissions are denied. Both the top and actual
child renderer intercept file choosers before input. The window cannot receive
seat mouse/keyboard input. Broker keys have no modifiers/global hotkeys/clipboard
API. Caller styles cannot cover the banner or create privileged owner dialogs.
Prompt text cannot change these checks.

WAL/FULL SQLite records UUID and SHA-256 admission before dispatch. Identical
retries return recorded state; changed payloads conflict. Restart, expiry or lost
acknowledgement becomes `uncertain`, never automatic redispatch. A new authorized
state action can inspect surviving windows. Mission end/cancellation or native
transport loss closes windows without stopping the independent Hermes service.
Native actions have a five-second deadline and limits of 120/minute and 1,024/mission.

Documents/input are redacted before transfer and pending only until dispatch.
Events contain operation/UUID/digest, not content or pixels. Capture bytes live in
controller memory for at most 15 seconds; only digest/size/dimensions persist in
its GUI ledger. Agent-side files remain private workspace artifacts. Screenshot
retention/encryption and unknown-secret/upstream-log handling remain separate
requirements. The tool returns paths, not base64 pixels into model/tool history.

## Verification and remaining scope

The HAOS suite covers SQLite reopening, replay/no-redispatch, stale native epochs,
deadlines, cancellation, budgets and screenshot audit exclusion. The real Unix
probe uses `SO_PEERCRED` and verifies denied peers, fake identities and unauthorized
methods. `npm run test:gui-broker --workspace @herald-os/desktop` executes production
native code with actual Chromium renderers: fills two fields, captures changed
pixels, checks a rendered marker and both renderer sandbox states; denies network,
chooser, clipboard, foreign-window/mission and malformed capability attacks.
CI retains only its source-bound receipt and disposable screenshot. This is a
providerless component test, not a real model turn or installed niri acceptance.

`npm run test:gui-integration --workspace @herald-os/desktop` connects the actual
production native broker to real private Unix controller sockets and the durable
mission database. It drives input/inspection/capture, denies forged sessions and
general control methods, loses one acknowledgement deliberately, refuses replay
and restarts the real controller process. The mission becomes blocked and its
audit survives. Its offline session and same-UID fixture are explicit; installed
agent/observer UID separation is covered separately by the kernel probes.

`HAOS_DISPOSABLE_SCREEN_TEST=1 npm run test:gui-wayland --workspace @herald-os/desktop`
requires an installed Weston and starts a private non-root virtual headless
Wayland compositor with a software renderer. Both real browser and socket gates
run as actual Wayland clients. The receipt checks actual mission `xdg_toplevel`
titles and surface commits, the compositor staying alive and all adversarial
checks. CI retains only bounded JSON and a disposable form screenshot, excluding
protocol logs, profiles, database and any host screen. Processes run in private
groups and are stopped on success, failure and timeout. This supports monitorless
component testing; it does not install a remote service or prove the installed
niri session, physical display, model turn or remote viewer.

The full GUI requirement remains **incomplete**: arbitrary host applications,
online/scripted browsing, compositor/workspace control, complete per-process
budgets, GUI owner setup and remote streaming need additional capabilities.
Credentialed Hermes graphical execution and matching installed Wayland evidence
remain required. This local browser enables report/form work without exposing the
host Wayland connection or privileged bridge. No Stable release is approved.

## Targeted niri placement

The same durable GUI action queue now accepts `locate`, `center` and `workspace`.
Every existing Chromium window has a fixed broker-generated title containing its
mission and window UUID. The native main process matches exactly one niri window
with that title **and its own kernel process ID**; a missing/duplicate match,
foreign PID, stale window, unsafe socket or unsupported compositor fails closed.
The compositor socket stays in native code, outside agent/renderer namespaces.

`locate` returns only that window's actual dimensions, focus flag and workspace
index, never other titles or compositor identifiers. `center` specifies its exact
niri ID. `workspace` selects an existing index 1–8 on that window's current output,
uses the stable workspace ID with `focus: false`, and rechecks actual placement.
No focused-window fallback, spawn, global key/pointer injection, portal, clipboard
or whole-desktop screenshot is exposed. Capture/input retain their renderer scopes.

The optional real niri fixture uses `HAOS_TEST_NIRI=1` with the existing
`scripts/test-gui-wayland.py`: niri is nested in the fixture's private Weston,
with two fixed workspaces, software rendering, offline networking and separate
process groups. Production niri's IPC controls and actual Chromium surfaces,
workspace moves, inputs/captures, controller restart and theme rollback are tested.
This remains a disposable component session, not an installed HAOS/model gate.

A Fedora 44 / niri 26.04 / Weston 15 container needs sufficient shared memory.
Its 64 MiB `/dev/shm` fixture exhausted available pages and Chromium exited with
SIGTRAP. A bounded 256 MiB fixture passed all 37 checks; its browser high-water
allocation exceeded 64 MiB. The harness records capacity/minimum free bytes,
retains original assertions/deadlines and keeps Chromium sandboxing enabled.
Installed registered host applications, verified systemd process limits, online
browsing and authenticated remote viewing remain open.

## Explicit owner application identities

`haos-owner application` now maintains a private root-owned registry for the next
host-application integration. A grant records an application ID/class, exact ELF
path under immutable `/usr`, SHA-256, fixed bounded arguments and intended memory/
runtime limits. Paths, parent ownership, file modes, set-ID bits, hard/symbolic
links, content changes, duplicate keys/IDs and policy size are checked. Grants
serialize under a private nonblocking lock and publish with the existing fsynced
atomic policy writer. A changed executable after an update requires a new approval.

## Private application execution engine

`application_session.py` adds a real private labwc Wayland session to the existing
application registry foundation. It runs an approved ELF and fixed owner arguments
as a separate unprivileged UID. Fixed `wlrctl`, `wtype` and `grim` helpers observe
actual toplevels, focus one unambiguous private window, enter bounded plain text
and approved keys, and capture actual JPEG pixels. No host Wayland/DBus socket,
input device, clipboard, caller command/path/environment, owner session or other
mission enters this session. Application-owned titles are not durable audit data.

`application_launcher.py` is an independently root-authorized library, with durable
UUID admission before submission. Its fixed systemd template uses DynamicUser,
RootDirectory, private network/devices, read-only `/usr`, empty capabilities,
NoNewPrivileges, bounded tmpfs, CPU/memory/tasks/runtime limits and cgroup-wide
termination. Mutable mission SQLite is opened in a fork after dropping to the
controller UID; only allow/deny returns to root. Cancelled, expired, pre-dispatch,
ambiguous and unsafe ledger identities fail closed. A repeated admitted action
is inspected rather than re-launched. Admission is not proof of application or
mission success.

The mandatory services gate runs a real terminal in an offline read-only disposable
Fedora 44 container with a private headless compositor. It focuses the actual
window, types a command, verifies the actual file content and changed capture,
and denies unsupported shortcuts, paths, commands and non-root control peers.
The application has zero effective capabilities and NoNewPrivileges. A separate
real root/fork/WAL probe denies cancelled/expired missions and private-path
substitution. Receipts contain component scope, source identity and checks, never
private screenshots, application output, profiles or database content.

**Still incomplete:** the root library has no public endpoint yet. The existing
owner status therefore continues to report launch unavailable. Installed systemd
execution/cleanup, queued capability proof, independent cancellation/revocation,
native presentation and credentialed Hermes execution must pass before enabling
the product path. The disposable container proves the private engine and UID
ledger boundary; it does not prove the proposed systemd unit or installed HAOS.
No caller-supplied environment, volume, credential or privilege field is accepted.

```sh
sudo haos-owner stop
sudo haos-owner application register mission-editor /usr/bin/APP --class editor
sudo haos-owner application status
sudo haos-owner application revoke mission-editor
```

`APP` must be an actual installed ELF application selected by the owner. There are
no default grants. Mutations require authenticated owner authority and fully stopped
execution. Re-registering an existing identity requires explicit revocation first;
audit records only ID/class/digest, not arguments. Class labels grant no system rights.

**This registry does not start applications.** Status explicitly reports host
launch unavailable. Mission process isolation, private Wayland/clipboard context,
resource enforcement and cancellation cleanup must be integrated before these
grants can authorize native execution. The real disposable root probe checks actual
ELF/file/UID/lock/update/restart/revocation behavior without executing the fixture ELF.
