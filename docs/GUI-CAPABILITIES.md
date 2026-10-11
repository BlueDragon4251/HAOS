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
General registered host applications, process isolation/limits, online browsing
and authenticated remote viewing remain open.
