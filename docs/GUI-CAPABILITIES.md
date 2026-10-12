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

The root launch library now verifies the running unit's actual dynamic UID and
kernel socket server PID before sending bounded private-session controls. A
replaced pathname cannot impersonate that control process. The session disables
dumpability independently of inherited NoNewPrivileges, preventing same-UID
applications from injecting its control process. Text is limited to 512 UTF-8
bytes per action to fit wtype's real per-key roundtrips within the existing
three-second helper deadline; the original Chromium tool retains its 4096-byte
limit. Multiple private windows deny implicit focus rather than choosing a dialog.

`run_application_unit.py` is a separate mandatory disposable systemd gate for
two real dynamic-UID terminal sessions, live input/capture, actual kernel cgroup
limits and cleanup of a `setsid` descendant. It requires a marked GitHub runner
with systemd PID 1 and never runs against the cloud host or a production policy.
An added gate is **not** evidence that it passed: its exact CI result must be
checked before claiming systemd execution or cleanup. Installed HAOS, queued
authorization, native presentation and independent revocation remain required.

Actual systemd launches deliver the fixed owner descriptor with LoadCredential,
not a base64 payload in world-readable unit metadata. Known credential patterns
and credential flags are rejected by the application registry; argv is never a
supported credential provisioner. Unknown secrets and all process/remote privacy
remain separate open requirements. Private launch descriptors are removed after
confirmed termination; bounded identity receipts remain for replay protection.

The headless seat keeps a fixed idle virtual keyboard and verifies its actual
Wayland keyboard capability before starting the app. This prevents first-key
loss while clients bind `wl_keyboard`; it sends no prepared input. The control
receipt binds the complete approved manifest, including argv, class and limits,
so re-registering the same ELF with changed rights invalidates old controls.

The trusted session journals only fixed startup phases/error classes. Child
applications, compositors and input/capture helpers have disconnected stdout and
stderr. The disposable unit test reads only these validated codes on a startup
failure, preserving diagnosis without copying command arguments, content or keys.
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

The real systemd fixture identified `SIGXFSZ` from foot’s default sparse 512 MiB rendering memfd under the retained 64 MiB file-size limit. The private session supplies `tweak.max-shm-pool-size-mb=32` through its own `XDG_CONFIG_HOME`; no host configuration or resource-limit relaxation is needed. The actual offline Wayland regression now also applies the same kernel file-size limit. See `docs/evidence/2026-10-11/application-shm-regression.json`; the separate root/systemd and installed gates remain necessary.

The Ubuntu `grim` package omits optional JPEG encoding. Capture therefore uses actual PNG output and the distro Pillow codec to produce a checked JPEG. Input, dimensions and output are bounded independently; captures remain ephemeral. The independent root action store records a nonce before execution and preserves uncertainty across restart. It accepts only the matching fresh `gui_actions` dispatch read as the controller UID, never an agent-supplied hash or identity. These components still need the controller/root-service and native presentation gates before general host launch is advertised.


## Controller-driven private applications

The existing `haos_gui` tool and WAL queue now also accept `app.start` with an
owner-registered `program` ID, then `app.state`, `app.focus`, `app.type`, `app.key`,
`app.capture` and `app.close` with the returned opaque `instance` UUID. No caller
argv, environment, compositor ID or file/clipboard API is accepted. App text is
limited to 512 UTF-8 bytes; registered arguments and limits stay owner-controlled.

The unprivileged controller dispatches these operations through the independent
`haos-applications.socket`/service, without waiting for Herald. Kernel peer UID,
fresh matching durable GUI dispatch, active mission, full executable/grant hash,
distinct dynamic UID and the actual control-server PID are independently checked.
A root nonce is durable before input. Reply loss stays uncertain. Native poll/ack
cannot consume or forge application actions; native reattachment cannot invalidate
them. The root monitor stops entire cgroups after cancellation, owner revocation,
changed grants, controller failure or broker restart. Its private rootfs imports
only read-only installed code/fonts, bounded temporary files and the application's
own home; it has a separate network and no host seat, owner files or shared sockets.

The two-application real systemd component gate passed at `7b801ed`, including
actual terminal results/captures, cgroup limits, escaped-child cleanup, other-app
survival and revoked/changed grant denial. Original component ZIP and fixed job
receipt are checked in `evidence/2026-10-11/application-systemd-ci.json`. The new
persistent-queue/root-client pipeline has a separate actual systemd gate. Production
broker sandbox, matching installed acceptance and native app presentation still need
their own receipts. Internet browsing, workspace/volume transfer, pointer control,
multiple private windows/workspaces and general owner desktop capture remain open.
No real model execution is claimed without configured provider credentials.

Herald’s mission detail now reads the same controller’s `applications.snapshot` API. It shows actual admitted program/instance IDs, fresh observed process/window receipts and the most recent real private-compositor JPEG. Frames expire after 15 seconds and are suppressed after mission cancellation. Expired/missing process evidence is labelled unverified; the view does not generate input or fake continuous video. It is read-only and cannot cover the fixed mission/program identity caption. Continuous capture, complete terminal telemetry and remote delivery remain separate work. The real queue/root/kernel application pipeline passed at `2fb65dc`; original unit/pipeline ZIPs are verified in `evidence/2026-10-11/application-pipeline-ci.json`. The native view has its own subsequent tests and installed acceptance remains required.

Private application units also bind their lifetime to the fixed independent root broker with `BindsTo` and `After`. PID 1 terminates their cgroups when that broker disappears, including SIGKILL; UI disconnection does not own these processes. The disposable systemd gate now checks guardian loss with a third actual application. The new assertion requires its own CI receipt before it is claimed successful.

`app.catalog` now lets the real Hermes tool discover approved program IDs/classes, approved executable hashes and fixed resource limits through the same independently authorized mission queue. It excludes argv, executable paths and credentials. The approval is not evidence that the current binary is unchanged; `app.start` still verifies actual bytes. The real persistent systemd pipeline checks catalog metadata and retains all seven original application-action assertions alongside the new discovery action.

The actual production-hardening gate first exposed a missing effective `CAP_SETUID` (permitted/effective `0x62`, bounding `0xe2`) before any application launch. The root service now explicitly carries its same four bounded capabilities across exec with NoNewPrivileges. Before mutable SQLite is opened, the fork resets keep-caps, drops groups/GID/UID, clears effective/permitted/inheritable/ambient sets, disables dumpability and verifies actual `/proc` identity and zero capabilities. Any failed reset is denial, not a privileged fallback. The four-capability assertion and actual service/WAL/application test remain mandatory; their new CI result is still required.

The subsequent full-hardening run returned actual systemd `200/CHDIR` before the session code ran. Broker `UMask=0077` had reduced newly created rootfs/home traversal directories to 0700. The allocator now explicitly publishes 0755 only for empty directories inside each private chroot; the enclosing broker runtime stays 0700 and receipts/launch credentials stay 0600. A real filesystem regression uses the production umask, retains the private enclosing directory and denies allocator reuse. Existing tempfs bounds/modes, process capabilities and all positive/negative gates are unchanged. The new full-hardening run must independently pass.

Native actions can now recheck `gui.lease` against their existing dispatched UUID/epoch and active mission, without consuming another pending action. Cancellation, completion, stale/foreign epochs and the existing 20-second queue age deny the lease. It grants no new operation or owner rights and is absent from the agent/renderer method sets. This supports upcoming cancellable theme work; existing browser/application timeouts are unchanged.
