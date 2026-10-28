# Hermes runtime

`haos-hermes.service` runs as `haos-agent` after first boot, networking and policy preparation. Source is pinned by `upstream/UPSTREAM.lock`. Image-only `build-runtime.sh` uses frozen upstream dependencies with reviewed web, messaging, anthropic, bedrock, vertex, azure-identity and matrix extras and Fedora's immutable `/usr/bin/python3.11`; RPM versions are recorded in `/usr/lib/haos/python-runtime.txt`.

The reviewed `linux/haos/runtime` overlay pins all runtime requirements with package hashes, including fixes for anyio, multidict, PyJWT, tornado and urllib3. Its preparation checks the exact upstream commit, original pyproject/uv.lock hashes and requirements digest before changing the conflicting PyJWT metadata. Installation requires hashes and `uv pip check`; installed versions and the source/requirements provenance remain in immutable `/usr/lib/haos/runtime-provenance`. Run `37818579514` verified the resolved dependencies with pip-audit, the actual pinned Hermes CLI and an expired-JWT regression. That CI result validates dependencies; the resulting updated Fedora image still requires its own build and guest evidence.

Writable home `/var/lib/haos-agent` appears as `/home/agent`; Hermes data is `/home/agent/.hermes`. `/var/lib/haos-workspace` appears as `/workspace`. Host homes, policy, raw devices, /sys and host sockets are not shared. Minimal passwd/group contains only the agent.

Backend is literal loopback `127.0.0.1:9119`. UI descriptor `/etc/haos/backend.json` points to the protected host token. Invalid managed configuration fails without unrestricted child fallback. Closing the UI does not stop the attached service.

The sandbox launcher passes the systemd credential through an inherited descriptor into a read-only file. The immutable sandbox-side launcher validates it and sets the backend environment before exec. The value is not included in Bubblewrap's public process arguments. The corresponding real kernel probe verifies file transfer and absence from process arguments; require a green result for the latest source commit.

The root-managed [network guard](NETWORK-POLICY.md) is an additional required startup dependency. Its socket-UID rules permit the literal backend and narrow DNS/reply traffic while denying other host/private destinations. Kernel and installed-guest acceptance of this new guard remain pending.

`runtime/probe_backend.py` starts the actual frozen `hermes serve` in fresh isolated state, verifies health and child PID identity, rejects absent/wrong tokens, and creates an authenticated runtime plus durable session through the actual JSON-RPC API. It terminates the child process group on all exits. At `ab2e521`, dependency run `37879468377` passed this real probe, the 80-package audit and JWT regression. The actual Fedora image builds at `ab2e521` and `e8dd0aa` also returned the successful backend receipt; build-time import/start failures now stop image creation. This proves the process/API/dependency contract, not installed systemd namespace startup or model execution.

Downloaded evidence for image `9e0d4a3` from acceptance `37842665549` shows successful installer completion and installed UEFI boot/firstboot, followed by the backend health assertion failing around guest uptime 303 seconds. The later host timeout did not identify the underlying failure. New guarded diagnostics capture bounded, token-redacted service state/journals and power off a failed disposable guest. Full installed-service acceptance remains open.

Current provider setup uses the separate private HAOS broker and owner credential wizard; see [provider setup](PROVIDER-SETUP.md) and [parity evidence](PROVIDER-PARITY.md). True provider keys and refresh tokens do not belong in agent state. Historical probe results below do not establish current live-provider or installed-system acceptance. Do not copy a human's credential/session directories. No provider-less probe is a real model mission. Bounded restarts do not prove unknown background work stopped; use [recovery](RECOVERY.md).

The replacement reuse `37878610539` completed with the exact cause: Hermes could not traverse the root-created runtime policy directory because systemd `UMask=0077` masked its requested group bits. The broker now explicitly applies root:agent-group 0750 to verified runtime directory inodes, retaining root:agent-group 0640 on the compiled policy. Mounted, writable, foreign-owned and symlinked directories are rejected. The real diagnostic/poweroff path worked; a rebuilt installed guest must still validate the correction.

The frozen runtime also carries one narrow functional overlay: `prepare.py`
verifies the exact pinned `agent/auxiliary_client.py` SHA-256 before inserting
HAOS-only MoA native streaming dispatch. All original dependency/input checks
run before writes. Build and provider-contract CI execute the actual pinned
MoA engine over Chat, Responses and Messages, including early deltas, native
stream abortions and scoped local SDK capabilities. Provenance distinguishes
the immutable Hermes base from the derived auxiliary source hash.


## Frozen Matrix crypto foundation (2026-10-25)

The same pinned Hermes lock contains its Matrix extra. Runtime builds and provider
CI now install that exact extra, then the unchanged hash-pinned HAOS overlay,
including MSAL 1.39.0. This adds nine locked packages without changing or removing
any existing runtime dependency. `source.json` records their exact versions;
`prepare.py` still rejects unreviewed extra sets, input hashes and dependency
metadata. No runtime package installer is introduced.

`probe_matrix_crypto.py` uses real mautrix 0.21.1, libolm bindings 3.2.16, the
pinned native Hermes crypto-state wrapper and actual SQLite crypto storage. Its
13 local self-room cases check encryption/decryption with Unicode and threads,
missing sessions, tampering, wrong-room data, message-index replay, identity/
device/sync/ratchet persistence after reopening, wrong pickle material without
account deletion, account namespaces and private file modes. Session creation
uses the actual SDK with no remote recipients; no shared flag is fabricated.
The probe is mandatory in builds and provider CI.

This is a crypto/dependency contract, not Matrix gateway enablement, remote
login, device verification, key exchange, network delivery or installed-system
acceptance. Matrix remains absent from HAOS's approved gateway set. Its native
sync path advances the batch before event dispatch and can swallow handler
errors; HAOS needs a durable dispatch boundary before using that transport.
Native automatic crypto-store reset/migration and unverified-device key sharing
also need independent HAOS guards before any real owner identity is connected.
No existing owner or recovery store is touched by these temporary fixtures.


## Private Matrix identity guards, still not enabled (2026-10-25)

`gateway_matrix.protect_crypto` now wraps one real native adapter instance.
The intended Matrix user and stable device must be explicit, and actual SDK
`whoami` must confirm both. The upstream substitution of a configured device
when the server omits it is insufficient. Crypto setup remains required; no
optional plaintext fallback is accepted on a dependency or identity failure.

Existing device changes, legacy pickle material, wrong pickle keys, symlinked
profiles and foreign/shared crypto files are refused. Login does not delete or
silently re-pickle an existing account/session store. Both signing and curve
keys must match the server's actual device-key response. Missing keys can be
published initially; existing mismatched keys cannot trigger a remote device
DELETE or replacement. Auto-bootstrap and recovery-file export are disabled;
only explicitly supplied private recovery material can invoke SDK cross-signing
verification. Unverified recipient devices and unsolicited key-forward requests
receive no key authority. These checks do not grant mission or room authority.

Fourteen local contracts use actual native auth/setup, real mautrix HTTP clients,
real server-response codecs, actual libolm accounts and private SQLite stores.
They cover initial publication/reopen, both key mismatches, changed/missing/wrong
device and wrong/revoked account, retained legacy material and actual symlink
refusal. The probe is mandatory in builds/provider CI. No real owner material is
used or deleted. Source receipt:
`docs/evidence/2026-10-25/matrix-identity-validation.json`.

Matrix is still absent from the approved HAOS gateway set. A stable isolated
profile factory, durable sync/dispatch, independent sender/room/thread grants,
safe outgoing obligations, owner CLI/GUI and further recovery remain required
before enabling it. Local device-key fixtures do not accept a real account,
remote device trust, federation, key exchange, delivery or installed system.


## Retained Matrix sync transport foundation (2026-10-25)

`gateway_matrix_sync` retains each bounded private sync response and its opaque
next cursor in one SQLite transaction before SDK callbacks run. This cursor
acknowledges retained transport data, not successful mission execution. Failed
pages remain separately pending while newer responses can arrive, including
missing to-device keys. Replaying an older page cannot roll the transport cursor
back. Authority snapshots are retained as evidence and never grant authority.

Private hooks await the actual SDK callback tree, including recursively created
background callbacks, and detect failures that the SDK/native dispatchers would
otherwise swallow. Missing crypto sessions retain encrypted input; later local
fixture keys permit actual decryption and replay. Cancellation retains input and
cancels outstanding callbacks. Raw pages compact only after callbacks finish.
Limited-timeline pagination markers and their original snapshots are retained
atomically before compaction; this does not implement their history fetcher.

Fourteen actual local HTTP/SDK/SQLite contracts cover commit ordering, repeated
cursors, reopen/replay, sibling/nested failures, newer protocol pages during an
old failure, malformed/stale cursors, a real SQLite trigger failure, namespace
separation, limited timeline markers, cancellation and late-key decryption.
The mandatory root gateway probe also runs real UID 65533/65534 child processes:
the agent cannot open private sync data, the gateway can resume it, and neither
can read the root-only owner canary. No UID/credential/authorization mocks or
additional skips replace these checks. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-sync-validation.json`.

Matrix remains disabled. This is a private transport component, not a complete
HAOS gateway or mission authorization path. The approved profile factory,
endpoint restrictions, sender/room/thread/device gates, limited-history fetcher,
mission/outbox integration and owner CLI/GUI remain required. No real account,
remote key exchange, federated delivery or installation is accepted by fixtures.


The sync increment also adds an actual SDK recovery-error contract: explicitly
supplied invalid recovery material produces only a fixed safe owner error and
never a verified flag. The native identity probe now has 15 cases (the earlier
14-case receipt remains bound to its earlier source).


## Private Matrix HTTP boundary (2026-10-25)

The guarded native identity setup now attaches `gateway_matrix_http.HTTPBoundary`
to its actual SDK client before authentication. Only the canonical owner HTTPS
homeserver and client API prefix receive requests. Actual whoami must confirm
user/device before private sync/key/account operations are allowed; a changed
token loses that confirmation. Impersonation/token query parameters, other
origins, redirects, unknown room reads and implicit/destructive writes are
refused. SDK request logging cannot expose an unapproved body/query before wire
admission. Native HTTP request encoding/response codecs remain in use.

Wire bodies/responses are bounded before JSON decode. Typed SDK errors retain
safe status/code and bounded Retry-After without vendor text or credentials.
SDK retries are forced off. Room sends require a separate explicit private
callback; account presence itself grants no send authority. This callback is
not a replacement for the still-pending HAOS binding/outbox implementation.

Seventeen actual local native-client HTTP cases cover confirmed whoami/sync,
encoded room reads/sends, refused reads/device deletion/creation/join/account
writes, single 401/429/500/302 responses, redacted errors, malformed/oversized
bodies, impersonation, token changes, origin mismatch, preserved deployment
prefixes and refusal of explicitly requested SDK retries. Existing 15 native
identity/crypto cases also pass through this boundary. Both probes are build/CI
requirements. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-http-validation.json`.

Matrix remains disabled as an HAOS gateway. No real account, remote verification,
key exchange, message delivery, installed boot or release is accepted here.


## Prepared Matrix mission admission (2026-10-25)

The private Matrix path now admits actual decrypted SDK events through the
independent HAOS sender/room/root-thread/device policy, retained raw input and
relay, and the actual mission engine. Only the exact decrypted object carries
private crypto evidence; serialized copies and network encryption flags do not.
Owner grants name both device public keys, original grant time and generation,
and explicit plaintext/mention rules. Unknown actors are rejected before SDK
profile/device lookup. Native Hermes still prepares text and source metadata;
HAOS preserves the approved thread and original 24-hour input-age boundary.
Recovery reopens retained input without renewing its authority or timestamp.

Eighteen local contracts exercise actual Olm/Megolm, SDK event decoding, pinned
Hermes text preparation, SQLite raw/relay persistence and real HAOS mission
creation. Twenty-three policy tests cover exact identities, device keys and
revocation. Full and minimal environments pass 1083 tests with two existing
skips; 37 real root/UID/socket checks pass, including rejection of prepared Matrix
publication by the installed owner backend. The other four gateways' thirteen
native regression probes pass. Evidence is source-bound in
`docs/evidence/2026-10-25/matrix-admission-validation.json`.

Matrix remains unavailable in installed setup: the prepared policy is selected
only by private implementation callers, never by root RPC, JSON, CLI or GUI.
The public controller still rejects it. Outgoing delivery, limited-history
recovery, complete profile lifecycle and owner setup remain required before
activation. These fixtures use disposable local identities and create local
fixture missions; they accept no external account, remote trust, inference,
message delivery, installation or release.


## Prepared Matrix outgoing text boundary (2026-10-25)

The next private component preserves pinned Hermes formatting/chunking and actual
Matrix SDK HTTP encoding, while rechecking the exact owner binding/room/thread
before every chunk and at wire authorization. Both the native adapter's broad
E2EE resend and the pinned HTTP transport's independent PUT retry are stopped.
A lost response, malformed receipt, 5xx, redirect or partial multi-chunk send
remains uncertain in the reopened actual HAOS outbox. A confirmed rate limit can
release a bounded retry; inspection never resends an uncertain obligation.
Unsolicited SDK writes outside the private outgoing context remain denied.

Twenty-one actual local SDK/HTTP/native/outbox cases cover exact flat/thread
routes, 400/401/403/404/413/429/500/302, lost connections with exactly one wire
send, malformed receipts, partial sends, revocation between chunks, forged
binding/scope/thread, unsolicited SDK sends and encryption downgrade refusal.
This is a prepared plaintext path only: current room encryption state must be
read successfully or explicitly report absence, and the owner must explicitly
allow plaintext. A stale SDK encryption cache cannot distribute group keys.
Encrypted outgoing messages remain refused until recipient/key-distribution
approval is implemented; inbound device approval is not reused as that proof.
Matrix remains disabled in installed setup. No external delivery is accepted.
Source-bound evidence: `docs/evidence/2026-10-25/matrix-delivery-validation.json`.


## Prepared Matrix limited-timeline history (2026-10-25)

The private recovery component now reads actual SDK `/messages` pages from each
retained limited-timeline marker. One call fetches at most 100 events; every
response is stored with the original grant snapshot in the private sync journal
before its independent history cursor advances. This transaction never changes
the normal sync cursor or native live-sync health. Failed native decoding remains independently replayable
from retained pages, even after the history cursor advanced or finished.
Version-two additive SQLite migration preserves existing transport/recovery data.

History uses current matching connector/room grants and their captured digests;
a new generation cannot reopen an old gap under renewed authority. Native text
admission still checks exact sender/thread, original timestamp, device proof and
capabilities. Empty pages with a new cursor do not terminate recovery. Wrong
start/room, repeated or cyclic cursors are refused without advancing. Safe
permission/rate-limit/transport statuses and bounded backoff remain persisted.
A failed SQLite cursor commit rolls back the retained page in the same real
transaction. No remote join, message send or automatic grant is involved.

Sixteen actual local SDK/HTTP/SQLite/native/mission cases cover old-schema reopen,
independent cursors, replay/unauthorized/expired input, empty pages, receiver
failure and reopen without another HTTP read, 401/403/404/429/500, wrong start or
room, repeated/cyclic pagination, real SQLite-trigger rollback and revoked
snapshots. All six preceding Matrix probes also pass. Full/minimal environments
each pass 1083 tests with two existing skips; 37 actual root/UID/socket checks
pass. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-history-validation.json`.

Matrix remains disabled in installed setup. The profile factory, supervision,
owner setup/lifecycle and independently approved encrypted outgoing key sharing
still need integration. Server-deleted messages, absent account permissions and
unavailable remote history cannot be recovered by local fixtures. No external
account, remote delivery, installation or release is accepted by these results.


## Prepared Matrix encrypted outgoing recipients (2026-10-25)

A separate private recipient guard now supports actual Olm distribution and
Megolm text answers through the pinned SDK. The current HAOS binding, exact room
and root thread are rechecked before key sharing and encrypted wire sends.
Only the binding's explicitly named recipient devices receive keys. Current
joined membership, both owner fingerprints, actual native device-signature
validation and distribution acknowledgement are required. Unknown devices,
mismatched signatures/fingerprints, local blacklists and missing signed one-time
keys refuse the result. A native session marked shared without all approved
devices being distributed to is insufficient. Device wildcard `*` is invalid.

Outgoing sessions are bound to the complete grant digest and session identity;
a changed grant or freshly reopened guard rotates only the outbound group
session. Account identity, inbound keys and recovery material remain retained.
Uncertain key distribution sends no result and never authorizes an automatic
resend of the old outbox obligation. Native/SDK/HTTP send retries remain disabled.
Direct SDK key distribution outside the private owner context has no authority.
The plaintext component still refuses encrypted rooms when this guard is absent.

Seventeen actual local SDK/HTTP/native/outbox cases use signed device keys,
real one-time keys, actual Olm distribution, a real SQLite crypto store and an
independent actual peer SDK to decrypt Megolm answers. They cover exact threaded
answers, missing one-time keys, unknown devices, fingerprint/signature failures,
local blacklist, departed recipient, 429/500, lost encrypted receipt with one
wire send, revocation between chunks, forged generations, lost key-share
acknowledgement, subsequent distinct authorized obligations, and a genuinely
closed/reopened SQLite database with a fresh SDK identity/guard. Full and minimal
environments each pass 1084 tests with two existing skips; 37 actual root/UID/
socket checks and the seven earlier Matrix probes pass. Build/CI require all
these native probes. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-recipients-validation.json`.

Matrix remains disabled in installed owner setup. Profile construction,
supervision, credential lifecycle and GUI need final integration before it can
be offered. These are disposable local keys and loopback HTTP contracts, not
verified real accounts, federated delivery, installation or release acceptance.


## Prepared Matrix profile lifecycle (2026-10-25)

The actual pinned Matrix adapter can now be constructed as a stable private
profile keyed by canonical homeserver, exact user and device. Credentials accept
an explicit access token and optional owner recovery material; native extra
configuration and implicit device discovery are refused. A real exclusive kernel
lease prevents two writers from using the same identity. Token rotation reuses
the existing account; changing device identity never resets its predecessor.
Native home and secret scopes are task-local, with safe mode enabled. Native
status transitions are persisted in the owned profile database because the SDK's
process-global background status writer cannot preserve a private task context.

Actual native authentication and crypto setup install the already tested input,
outgoing recipient and history guards before retained initial sync. Live sync
uses bounded native long polling; an independent recovery worker reopens pending
pages, raw input and history. Missing decryption keys do not starve newer sync
responses. Original grant snapshots and timestamps survive recovery. Superseded
or disconnected SDK clients lose the private HTTP boundary. Auth refusal stops
the adapter; safe error status, pending counts and Retry-After survive closure
and a fresh factory. Closing cancels an in-progress native login, stops workers,
closes SDK/SQLite handles and releases the lease even if status persistence fails.
It retains crypto, account, inbound and recovery files.

Twenty actual local native SDK/HTTP/SQLite/profile/mission/outbox cases exercise
the full connect/reconnect path, same-account token rotation, exclusive lease,
private files/home/status, plain and actual Olm/Megolm answers, auth refusal,
persisted rate limits, wrong device, pending-key recovery alongside live sync,
concurrent close during login, owner revocation and a real SQLite status failure.
Nineteen additional standard-library credential contracts run without Hermes.
Full/minimal suites each pass 1103 tests with two existing skips. Thirty-eight
actual root/UID/socket gateway checks pass, including a new real UID 65533/65534
lease/file/canary check with no identity or authorization mocks. All preceding
native Matrix probes also pass. The new profile probe is mandatory in build/CI.
Source-bound evidence: `docs/evidence/2026-10-25/matrix-profile-validation.json`.

Matrix is still unavailable in installed setup: the public controller and owner
CLI/GUI remain closed until the service/publication/setup paths are integrated.
These private loopback fixtures are no real account, external delivery,
installation, boot or release acceptance. No existing owner data is removed.


## Matrix owner setup and service integration (2026-10-25)

Matrix now has a reviewed HAOS text setup path alongside Telegram, Discord,
Slack and Mattermost: five of 22 adapters have owner provisioning and native
text integration. This supersedes the earlier private-only activation guards.
The public policy applies the same exact sender/room/root-thread/device rules
used by the native contracts. Complete canonical homeserver/user/device
credentials are required; a token alone or native extra overrides cannot be
published. The service constructs the guarded stable profile with current owner
authority and private raw storage, and closes it on service shutdown.

The graphical and owner CLI paths store tokens/recovery material privately,
expose exact route/capability/device choices, and never auto-approve a discovered
device. Public device discovery runs through the actual SDK as the gateway UID
with confirmed whoami and native self-signature validation; the owner must still
compare the fingerprint with the physical device. Credentials travel to this
short-lived helper only over stdin, not argv/environment. Discovery stops the
gateway until the owner restarts it. Unknown devices receive no result keys.
A fresh actual encrypted answer remains unreadable by an independent unapproved
SDK device of the same account, while the selected device can decrypt it.

Owner rotation/removal withdraws bindings and private configuration atomically;
recovery/account files remain retained. Removal is local HAOS withdrawal, not a
claim that the homeserver revoked its account token. Revoke obsolete tokens in
the Matrix account as appropriate. Stopped-owner inspection includes safe
profile/auth/rate/history status and retained-page counts; it reveals no message
content or private credentials. Offline input/outbox reconciliation accepts exact
Matrix event IDs, preserves original input age, and never sends on inspection.

In the GUI choose Matrix, enter a separate service account's existing access
token, canonical HTTPS homeserver, exact @user:server and stable device ID.
Optional recovery material must already exist; setup does not reset identities.
Join the service account to the intended rooms yourself. For each allowed sender,
enter @sender:server and !room ID, keep scope empty and choose the existing $root
thread or leave it empty for flat messages. Load signed devices, compare their
Ed25519 fingerprints out of band and explicitly stage the desired devices.
The signature also binds Curve25519. Then save the route and selected rights.
Plaintext defaults off and mentions default on. Restart the gateway after pairing.

Equivalent owner console setup (replace all example public IDs/key placeholders):

```sh
sudo haos-owner gateway setup matrix-main matrix
sudo haos-owner gateway matrix-devices matrix-main '@owner:example.org'
sudo haos-owner gateway pair phone matrix-main '@owner:example.org' '!room:example.org' \
  --identity personal --matrix-device PHONE ED25519_PUBLIC_BASE64 CURVE25519_PUBLIC_BASE64 \
  --capabilities create read
sudo haos-owner gateway start
```

The setup command asks for private material through protected input. Optional
`--allow-plaintext` and `--no-require-mention` are explicit Matrix exceptions;
`--thread '$root-event'` selects one existing root thread. Invalid or self-echo
service-account bindings are refused. No public webhook, automatic invite join,
interactive native tool approval or arbitrary plugin is enabled.

Local validation covers 1118 full/minimal tests with two existing skips, 40 real
root/UID/socket gateway cases, 165 actual native Matrix cases across ten probes,
13 regression probes for the existing gateway paths, and seven real Tk Matrix
handoff/layout cases at each of 1280x800 and 640x480. Existing complete GUI
fixtures also pass at both sizes. Build/CI require native account discovery and
GUI tests. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-owner-integration-validation.json`.

These contracts use disposable accounts/keys and loopback HTTP. They confirm no
external Matrix delivery, physical device trust, installed service/boot or
release. Full media/voice, the remaining 17 adapters, Android, phone firstboot
and installed OS/artifact acceptance remain unfinished.

### Public Python package permissions

The image installer installs only `linux/haos/haos` through
`runtime/install_package.py`: root-owned directories use `0755`, regular public
code uses `0644`, independently of the checkout umask. Links and special source
files are refused; destination symlinks and multiply linked files are refused.
This operation does not traverse provider credentials, Matrix profiles, owner
state or recovery stores. This fixes a reproducible restrictive-checkout import
failure; it is not evidence of the cause of historical HP or installed-QEMU
failures.

The provider-contract workflow additionally runs the actual Matrix account
helper as root, an unrelated UID and the gateway UID in a fresh disposable
container with networking disabled. Seven local HTTPS/SDK cases verify the
process gate, system CA verification, exact account/device identity, signed
public device discovery and redacted 401/429/signature errors. Discovery still
requires separate owner approval; this fixture does not accept a live account,
external delivery, installed boot or physical device trust.

### Prepared ntfy ingress (not publicly enabled)

`gateway_ntfy.py` now prepares the actual pinned bundled ntfy text decoder
behind the private native inbox. A prepared grant explicitly trusts **all
publishers to one exact topic** (`trust_topic_publishers: true`). ntfy has no
independently authenticated individual sender identity: publisher-controlled
titles, sender labels and user fields never become HAOS principals. A server
and its topic ACL must supply the topic's trust boundary. Public owner setup,
`GatewayPolicy` and runtime factory still reject ntfy.

Before native decoding, HAOS requires an exact topic and stable event ID,
original server timestamp newer than the grant, captured grant generation and
bounded plain text. Attachments, actions, click targets, encodings and native
echo-tagged messages are refused. The raw event and exact owner route commit
to SQLite before the actual native decoder runs. Failed admission remains
pending across database reopen; native in-memory TTL dedup cannot swallow its
retry. Revocation is checked again at replay and admission. The native callback
cannot bypass retained capture.

`probe_ntfy_ingress.py` has 24 local cases through that actual decoder and
SQLite journal, including reopen/retry and revocation. It is required by the
image build and provider-contract CI. This is prepared ingress, not a sixth
usable gateway: the continuous authenticated HTTP transport, persistent stream
cursor/recovery, conservative output delivery and complete owner GUI still
need integration. No external subscription or publication was performed.

### Prepared ntfy continuous transport and recovery

`gateway_ntfy_transport.Subscription` adds a bounded private HTTP subscription
with the actual pinned ntfy adapter's authentication and decoder. The immutable
owner-selected HTTPS server/topic and private credential are bound to the
captured grant. HTTP proxies and redirects are disabled. The reader admits
small newline-delimited events immediately during the open stream, checks
bounded UTF-8/JSON frames (including duplicate keys), and refuses compressed,
partial or oversized records. The server's message cache is requested with
`since`; per-message admission still enforces original grant age independently.

The native raw inbox commits before the separate cursor update. A crash or
cursor-write failure can therefore cause replay, but cannot advance beyond an
unsaved obligation. The cursor and bounded retry deadlines survive database
reopen; 401/403 and missing sources stop automatic retries, 429 retains a bounded
deadline, and vendor bodies never become status text. Credential or grant
changes stop the old subscription. `run()` maintains continuous receive and
pending replay in separate tasks, including real reconnects; `close()` cancels
both and closes the HTTP client. No external publishing is implemented here.

The mandatory build/CI probe has 19 real loopback HTTP cases, including early
stream delivery while the end is held, durable reconnect, an actual SQLite
cursor fault, independent replay while a connection is open, and cancellation.
Only the fixture replaces the reviewed HTTPS origin with loopback HTTP. This
is not TLS/live-account acceptance. ntfy remains disabled in public setup and
runtime until output delivery, owner GUI and complete lifecycle integration
are finished; the number of reviewed public text gateway paths remains five.

### Prepared ntfy native answer delivery

`gateway_ntfy_delivery.Publisher` now executes the actual pinned adapter's send
codec through a private per-task publication capability. Only the exact current
owner-approved topic can receive an answer; the native `publish_topic` override
cannot redirect it. The owner grant and credential identity are rechecked for
each chunk and immediately before each HTTP POST. Direct native send calls and
unscoped HTTP calls have no publication authority.

UTF-8 chunks stay within 4096 bytes without truncating Unicode or dropping a
suffix. Only a bounded native server receipt with matching topic and a safe
real event ID proves delivery; missing IDs cannot use the upstream random-ID
fallback. Reflected credentials are refused as public receipt IDs. Vendor
error bodies never reach native logging. A known first-chunk 429 can be retried
by the durable outbox after its bounded delay; lost/invalid receipts, 5xx,
redirects, or any successful chunk before a later refusal remain uncertain.
There is no automatic resend of an uncertain complete reply.

The mandatory build/CI probe has 29 actual codec/HTTP cases, including six
reopened real MissionStore/GatewayEngine outbox checks and revocation between
chunks. These are local fixtures, not external ntfy publication. Public ntfy
setup/runtime remain disabled pending integrated private profile, service
lifecycle and owner GUI. Prepared replies currently target the same explicitly
approved topic; separate publish-topic management is not yet enabled.

### Prepared ntfy private profile lifecycle

`gateway_ntfy_profile.build` now composes the actual bundled adapter, durable
source admission, continuous subscription, independent pending replay and native
answer publisher. It accepts only the private token, canonical HTTPS server and
literal topic. A stable per-server/topic directory and private home use `0700`;
a single-link `0600` file with an actual nonblocking kernel flock prevents a
second active identity profile. Existing stores are retained across close,
fresh factories and explicit token rotation.

Hermes imports and adapter construction occur inside the private task-local
home/secret scope. Stream workers inherit that scope; sends enter it explicitly.
An actual lifecycle fixture initially reproduced global-home bootstrap writes
when imports occurred before entering the scope. Those imports were moved
inside it. The native process-global background status writer is replaced only
on this adapter instance; actual transport/health/error/retry transitions are
persisted synchronously in the service-owned inbox. No unrelated process-global
Hermes home is created or modified by the validated lifecycle.

Connect waits for the authenticated HTTP stream; disconnected profiles have no
send capability. Only exact current retained route metadata can send through
the native publisher. Disconnect closes both HTTP directions and workers;
concurrent profile close releases the lease once. Real 401 state survives
restart and blocks automatic credential retry; explicit credential rotation
creates fresh credential-bound transport state without removing earlier
receipts. Owner revocation stops workers and preserves its safe error code.

Four mandatory native probes now cover 24 ingress, 19 continuous transport,
29 delivery (including six reopened real mission outboxes), and 21 profile
cases: **93 local contracts**. Twelve additional standard tests include a real
`python -I -S` import without site packages/upstream and invalid private
configuration cases. Full and minimal suites each pass 1130 tests with two
existing skips. Public ntfy owner setup, GUI and production service routing
remain disabled and unfinished. These fixtures accept no external account,
subscription/delivery, installed service/boot or final release artifact.

### ntfy owner setup and service integration (2026-10-25)

ntfy is now publicly selectable through owner publication, CLI, graphical setup
and the private gateway service factory. This supersedes the earlier prepared-
only status above. There are **six reviewed text gateway paths**: Telegram,
Discord, Slack, Mattermost, Matrix and ntfy. The other 16 adapters and complete
media/voice integration remain unfinished; no live account/delivery is accepted
by these local fixtures.

In the graphical gateway page choose ntfy, enter an explicit system-trusted
HTTPS server, literal private topic and protected API token or `user:password`.
Native Basic auth supports UTF-8 passwords, internal spaces and colons; Bearer
tokens remain header-safe ASCII. The GUI explains the necessary server-side
ACL: a secret topic name is insufficient. **ntfy has no independently verified
individual publisher identity.** Its owner grant explicitly trusts every
publisher allowed to that exact topic, with the selected HAOS identity and
capabilities. All those publishers share that identity's missions when granted
read rights. Configure trusted publishers on the server first.

Sender and chat are filled from the topic; scope/thread fields are disabled.
An unchecked publisher-trust box cannot submit pairing. Topic, server or
connector edits reset that confirmation. Pairing additionally checks that the
submitted topic and server match the actual saved private connector; unsaved
endpoint edits cannot silently bind another server. Nonsecret saved endpoint
metadata can be reviewed without returning the token. Credential changes
withdraw previous grants before the atomic publication. Renewed grants receive
a fresh generation and time boundary; legacy grants without one cannot start
a subscription or capture input.

The CLI uses protected credential prompts, never a token argument:

```sh
haos-owner gateway setup ntfy-main ntfy
haos-owner gateway pair ntfy-owner ntfy-main private-topic private-topic \
  --identity ntfy-owner --capabilities create read --trust-topic-publishers
haos-owner gateway start
```

Input and answers currently use the same explicitly approved topic. The native
`publish_topic` override cannot redirect a reply. Private profiles and inboxes
are opened by the service, not by the agent. Owner ingress inspection exposes
only validated status/receipt metadata and retry deadlines; it never sends.
Source IDs and receipts reflecting raw or encoded private credentials are
refused, including before a source ID could become a `since` query parameter.
UI recovery shows actual auth, stream-format, retry and revocation errors.
Local removal/revocation does not claim server-side token revocation; use the
ntfy server's account administration for that independent action.

At the source hashes in `ntfy-owner-integration-validation.json`, full and
minimal suites each pass **1139 tests with two existing skips**. There are
**47 actual root/UID/socket gateway cases**, including a real child UID that can
read its group-approved policy but cannot read the private credential file.
Native ntfy probes pass **26 ingress + 20 transport + 32 delivery/outbox + 23
profile = 101 cases**. Native Basic auth and error redaction run over actual
loopback HTTP. Eleven real Tk cases pass at each 1280x800 and 640x480; existing
complete GUI fixtures and seven Matrix owner GUI cases pass at both sizes.
Ten native Matrix probes (165 cases) and 13 other gateway probes still pass.
Build/CI require the probes. These are no external subscription/delivery,
physical owner-seat, installed service/boot, hardware or release acceptance.

The explicit owner action `haos-owner gateway retry-ntfy-auth ntfy-main` (or
“ntfy-Anmeldung erneut erlauben” in the GUI) stops the gateway and clears a
persisted 401/403 block through the separate gateway-UID offline helper. It
preserves cursors, credentials, grants and raw message payloads and performs no
network request. Status update and private owner audit are one transaction;
real SQLite audit failure rolls both back. A subsequent manual service start
must still authenticate successfully with the actual server. This allows
recovery after server/account correction without rotating an otherwise valid
token or regranting sender authority. The actual native lifecycle fixture also
checks same-token reauthentication without duplicate admission.

ntfy timestamps have second precision. Originals that cannot be proved newer
than the exact owner grant remain excluded; messages in the grant's same second
can therefore require a fresh submission. Server cache retention, deleted
messages and server clock correctness remain real recovery limits.

### Prepared Home Assistant context/entity ingress (not publicly enabled)

`gateway_homeassistant_ingress.py` now prepares the actual pinned Home Assistant
state-change decoder behind independent user/entity grants and the private
native inbox. The upstream decoder's synthetic `homeassistant` sender and
wall-clock-generated message ID are not used as HAOS authorization/replay
identities. A prepared event requires an exact context user ID, entity ID,
matching new-state context, timezone-aware original timestamps and a captured
owner grant generation. Stable message IDs derive from the original context,
entity and source timestamps. Payload user labels cannot authorize a sender.

The raw event commits before native decoding and relay admission. Native
cooldown state cannot consume a failed durable attempt; a real database reopen
and elapsed retry preserve the obligation. Regrant/revocation is checked before
capture, replay and admission. Unknown entities/users, service contexts with no
user, malformed state/attribute types, missing/naive/future/pregrant timestamps,
and direct unretained native callbacks are refused.

The mandatory build/CI fixture passes 24 actual native decoder/SQLite/relay
cases; eight standard tests also cover closed public policy, exact grants and
real imports without site packages/upstream. Full/minimal suites pass 1147 tests
with two existing skips. This is prepared decoding only: authenticated bounded
WebSocket transport, account proof, recovery/history, conservative native
notification delivery and owner GUI remain unfinished. Home Assistant remains
outside public owner setup and runtime routing, so the reviewed text-gateway
count stays six. No authenticated HA transport, live account, external event
or notification, installed service or hardware is accepted by this fixture.

The private gateway token must not enable unrestricted Home Assistant device
control in the agent. Native smart-home tools are not authorized by this
prepared decoder; any future device control needs its own explicit bounded
owner capabilities. Service/system event contexts also need separate explicit
policy rather than silently mapping unknown senders into a trusted principal.


### Prepared Home Assistant authenticated WebSocket boundary

The actual pinned adapter now performs its native `auth_required` / token /
`auth_ok` / `subscribe_events` exchange through a private instance boundary.
Authority starts only after an exact matching result ID with boolean success;
early events, wrong/bool IDs and duplicate JSON fields cannot complete it. The
canonical HTTPS/WSS origin is fixed, redirects/proxies/TLS overrides are refused,
and frames are limited to 64 KiB. Invalid remote bodies never enter native
handshake logging. Token or owner-grant changes revoke the socket proof,
including changes while an acknowledgement is pending. Superseded sockets
cannot borrow or revoke a newer socket's proof.

The retained reader calls the actual native state codec only after raw SQLite
admission. Socket EOF revokes health. Native standalone notification fallback,
REST writes, other origins and WebSocket device-service calls are denied;
notification delivery is still unimplemented. The handshake has a 30-second
production deadline, closes interrupted/cancelled connections, and bounds
WebSocket close to five seconds before aborting the pinned response transport.

`probe_homeassistant_transport.py` passes 23 real local aiohttp/native handshake
and input cases. It tests a real held handshake with a deliberately shortened
0.05-second fixture deadline (not a latency benchmark), caller cancellation,
wrong subscription routing and actual message-too-big close code 1009. Only
the fixture replaces WSS with loopback WS. It confirms no live/TLS/account,
notification, agent device tool, installed service or hardware acceptance.
Home Assistant remains publicly disabled; six text gateway paths are active.

### Prepared Home Assistant native notification delivery

The pinned native adapter creates persistent notifications shared by the whole
Home Assistant instance; it has no recipient-user argument. The prepared
publisher therefore requires **explicit boolean owner approval** through
`homeassistant_shared_notifications: true`, plus read authority for the exact
current source binding. Without that approval, it performs no POST. This is
not silently equivalent to a private reply to one user/entity. Public setup is
still disabled until that distinction is presented in the actual owner GUI.

`gateway_homeassistant_delivery.Publisher` executes the actual pinned send
codec through one fixed private service endpoint. A stable per-outbox/chunk
notification ID is added to that approved native payload; other REST/device
services and unscoped native fallback have no authority. Complete Unicode text
is chunked without the native 4096-character truncation. Current owner grant
and private token are rechecked throughout publication and receipt validation.

Native send returns a random UUID even on an empty HTTP 200 response, so it is
never accepted as a remote receipt. A separate private observer executes the
actual native authentication/subscription exchange, then only the fixed
`persistent_notification/get` read. It returns no unrelated notifications to
the agent. Delivery requires one actual matching remote notification ID, title
and complete chunk text. The API shape and shared audience were read from Home
Assistant Core commit `9eb964b8b95fddc61ec4841277fbce7ce32dc586`; the read-only
reference manifest is included in runtime provenance, not vendored as code.

The mandatory local probe has 22 actual native REST/WS/send cases including six
reopened real mission outboxes. Missing/wrong/duplicate receipt data, lost
responses, redirects, auth failures and 5xx remain uncertain; a partial reply
followed by 429 does not retry the whole message. The notification verification
read remains bounded (including the 64-KiB WS frame limit); excessive server
notification collections cannot fabricate success. Full/minimal suites pass
1151 tests with two existing skips. Actual root/UID/socket regression remains
47 cases. Home Assistant still lacks full private profile/recovery/history and
owner GUI integration, and stays publicly disabled; six text paths remain
reviewed. No external notification, actual server/account/TLS, installed boot,
hardware or release acceptance is claimed. Device-control tools remain denied.
### Prepared Home Assistant receipt connection recovery (2026-10-25)

After baseline `cd7002f398d56196a276fc976346971cd8e9fdfb`, the private
notification witness closes its authenticated WebSocket and session whenever
a receipt is unconfirmed, malformed, or interrupted. Successful receipts may
reuse the connection. A distinct subsequent outbox obligation performs a fresh
native authentication/subscription handshake after failure; this does not retry
the previous uncertain publication. Cancellation still propagates to the caller.

The native delivery probe now passes 26 cases, including missing, wrong-ID,
duplicate-proof and caller-cancellation recovery on actual loopback REST/WS
connections. The unchanged ingress/transport probes pass 24/23 cases. Full
and minimal-runtime regression each pass 1151 tests with two existing skips
and the existing local backup-file exclusion; no CI skips were added. Source
hashes and limits are recorded in
`docs/evidence/2026-10-25/homeassistant-witness-recovery-validation.json`.
Home Assistant remains prepared, with no public GUI/profile integration or live
delivery acceptance. A native live WebSocket alone cannot recover unseen events
from a disconnect: the server history API omits the direct event context user,
so history is not silently granted the authority of an authenticated live event.

### Prepared Home Assistant isolated lifecycle (2026-10-25)

After `505eb657b9690f07f220ae61b7b21363d406986a`, a private prepared profile
constructs only the pinned bundled adapter inside its isolated Hermes HOME.
Canonical service-owned 0700 directories and a private single-link kernel lock
prevent parallel use. Credentials are validated before native imports; no native
plugin manager, automatic sender pairing or device-control tool is enabled.

The lifecycle uses the reviewed native WebSocket handshake/reader, independent
durable raw-input replay, bounded reconnect delays and separate notification
receipt verification. An owner-grant change revokes the running profile instead
of granting old work new authority. Authentication refusal persists across
profile close/reopen; rotating credentials creates a new authentication identity
while preserving the private HOME. HTTP 429 Retry-After deadlines persist across
close/reopen. The native global status writer is disabled; safe status is written
synchronously into the private native inbox. `gap_since` records an interval
whose unseen remote events cannot be recovered from native HA state history.
It is never cleared merely because a live connection returns.

Twenty-two actual local profile/WS/SQLite/kernel-lock cases pass, including a real
raw-journal reopen, failed relay admission retried while the live socket is idle,
credential rotation, concurrent close and shutdown during a rate-limited start.
Transport/ingress/delivery regression passes 24/24/26 cases. Full and minimal
HAOS regression each pass 1161 tests and two existing skips, with the existing
local backup-file exclusion. The 47 existing actual root/UID/socket/recovery
checks pass in a disposable network-isolated container. No CI skips were added.
The profile probe is mandatory in runtime build and provider-contract CI.

Evidence: `docs/evidence/2026-10-25/homeassistant-prepared-profile-validation.json`.
Public runtime/CLI/GUI wiring, owner authentication-retry management and full
remote replay are still unfinished. This is not a seventh public gateway, a live
HA-account/TLS/notification acceptance, or an installed service/boot acceptance.

### Prepared Home Assistant owner recovery contracts (2026-10-26)

All five CI gates passed for `be08b7530c4645591924fb485537799506908b33`.
The next source change adds bounded safe Home Assistant metadata to the offline
raw-inbox inspection and a prepared, audited authentication-recheck function.
Inspection returns only receipt/status fields, including `gap_since` and
`unseen_remote_history_recovered: false`; payload content and credentials stay
private. Invalid status, connector and time values fail closed.

The recheck clears only authentication-refused rows for the explicitly selected
Home Assistant connector. It preserves rate limits, revocations, gaps, raw
payloads and attempts. An actual SQLite audit-storage failure rolls the decision
back atomically. The function performs no network I/O: the subsequent profile
start still performs the real native authentication and subscription handshake.
No gap disappears after a successful authentication.

Full/minimal suites each pass 1172 tests with two existing skips and the existing
local backup-file exclusion. Forty-nine actual root/UID/socket/recovery checks
pass in the network-isolated disposable container: the two new cases verify
gateway UID 65534 can make the audited local decision, agent UID 65533 cannot
open its journal, neither identity can read the root-only canary, and audit
failure preserves the authentication block. The native profile probe passes
24 cases including the actual authentication after the prepared owner decision.

Evidence: `docs/evidence/2026-10-26/homeassistant-prepared-owner-recovery-validation.json`.
The new recheck function is not yet exposed by the recovery helper's main action
dispatcher or a CLI/GUI button. Public runtime/owner setup integration and remote
history recovery remain unfinished. There are still six public text gateways;
these are local contracts, not live or installed acceptance.

### Home Assistant HTTP-date retry deadlines (2026-10-26)

After `b9d88a44ce263207493d4202f3b7ddb3ad152f03`, the private WS and
notification paths accept both standard Retry-After forms: integer seconds and
timezone-aware HTTP dates. The shared gateway helper uses the existing bounded
provider parser, rejects malformed/nonfinite/control-bearing values and avoids
publishing a reflected private credential as timing. Delays remain bounded to
1–86400 seconds; invalid/missing values retain the route's fixed safe default.

Actual loopback native probes pass 25 transport, 27 delivery and 25 profile
cases. A future HTTP date sets the actual outbox retry and survives private
profile close/reopen without an early network request. The two forms retain
the existing conservative ambiguous/partial-publication behavior. Full/minimal
suites each pass 1190 tests and two existing skips with the unchanged local
backup-file exclusion. Forty-nine actual root/UID/socket/recovery cases pass;
there are no additional CI skips. Exact source hashes and limits are recorded
in `docs/evidence/2026-10-26/homeassistant-http-date-retry-validation.json`.
Other gateway transports are not yet switched to this shared parser by this
change. Home Assistant remains prepared, without public setup or live acceptance.

### Public gateway HTTP-date retry deadlines (2026-10-26)

After `04f96b1b476ec359cfbc0c314d5c96d2b142b3f2`, ntfy subscription/publish,
Matrix private HTTP and Mattermost read/post also use the shared bounded
Retry-After parser. Valid native Matrix `retry_after_ms` keeps precedence;
missing, invalid or negative native values fall back to the checked HTTP header.
Private credential reflection cannot become public timing metadata. This changes
timing only: partial/uncertain publication still has no automatic whole-reply retry.

New actual HTTP cases verify ntfy's persisted stream deadline across reopen,
ntfy single-post deferral, Mattermost reopened pending outbox and history SQLite
deadline, and Matrix native-millisecond precedence/HTTP-date fallback. The history
fixture advances only its explicit recovery clock after checking no earlier GET
can occur; production clocks/deadline logic are unchanged.

Ten affected native probes pass 212 cases: ntfy transport/delivery/profile
21/33/23; Matrix HTTP/profile/delivery/history 20/23/21/16; Mattermost
delivery/history/ingress 18/16/21. Full/minimal suites each pass 1190 tests and
two existing skips with the unchanged local backup-file exclusion. Forty-nine
actual root/UID/socket/recovery cases pass, without additional CI skips.
Source hashes, individual case receipts and limits are in
`docs/evidence/2026-10-26/public-gateway-http-date-retry-validation.json`.
This is local protocol validation, not actual remote delivery, live TLS/account,
installed service/boot or artifact release acceptance. Public gateway count
remains six; Home Assistant remains prepared.

### Prepared Home Assistant shared dispatch contracts (2026-10-26)

After `8a77dcaa7a0d65880765e321408931e62d9dadb6`, the common adapter factory
accepts a prepared Home Assistant profile only with the exact private parent,
connector, independent policy callback and native inbox context. Missing or
arbitrary contexts fail before SDK imports/network access. Public GatewayPolicy
still rejects Home Assistant, so this does not expose an unfinished owner setup.

Common delivery metadata now carries the controller's stable outbox ID to the
private notification capability. The native profile probe creates a real mission
and outbox, uses the actual shared dispatch metadata, sends through the pinned
adapter and authenticated receipt witness, acknowledges the obligation and checks
the delivered state after reopening MissionStore. Twenty-nine profile cases
pass, including the real shared service supervisor: a persistent auth refusal
cannot be bypassed by reconnect, and stop joins workers/closes native sessions.

Public Slack/Matrix/Mattermost delivery probes now use the same production
metadata helper with actual persisted outboxes; all 14/21/18 cases pass. Full
and minimal suites each pass 1190 tests and two existing skips, using the
unchanged local backup-file exclusion; all 49 actual root/UID/socket/recovery
checks pass. No CI skips were added. Exact source hashes and contract receipts
are in `docs/evidence/2026-10-26/homeassistant-shared-factory-validation.json`.
The public service policy, CLI, GUI and recovery-helper action wiring remain
unfinished; no seventh public gateway, external notification, installed service
or release acceptance is claimed.

### Slack current owner authority for every native write (2026-10-26)

A new actual SDK/HTTP/outbox negative fixture failed on production source
`f640a04081505dc091ef3b777b0e70f65352068e`: a forged binding digest was
ignored by the Slack delivery wrapper and the response was marked delivered.
Workspace/CI success on that predecessor did not establish this missing contract.

Slack now requires the current independent owner connector, binding digest,
chat/workspace/thread and read permission before native dispatch, and rechecks
the captured capability before every SDK operation in the delivery context.
Changing the caller's metadata cannot grant an in-flight operation a new epoch.
Missing/invalid context fails before HTTP. Revocation after one accepted chunk
prevents the second chunk and preserves uncertain delivery; revocation after an
explicit formatting refusal prevents the native fallback and remains failed.

Nineteen actual native Slack delivery/outbox cases pass, including missing/forged
binding, unavailable policy, between-chunk revocation and formatting-fallback
revocation. Ingress/history regression each pass eleven actual native cases.
Full/minimal suites each pass 1201 tests with two existing skips and the unchanged
local backup-file exclusion. Fifty-one actual root/UID/socket/recovery checks
pass: two new gateway-UID processes admit the valid root-owned policy, observe
an actual atomic owner-file replacement and reject withdrawal/epoch changes.
The unprivileged identity cannot read the root-only canary. No CI skips were added.

Exact production/fixture hashes, the failed predecessor fixture and successful
contracts are recorded in
`docs/evidence/2026-10-26/slack-current-delivery-authority-validation.json`.
This does not certify live Slack credentials, external delivery, installed boot
or release artifacts. Telegram/Discord delivery authority is a separate check;
this change does not claim to add the same guard to those transports.

### Telegram/Discord current delivery authority (2026-10-26)

The same actual SDK negative fixture reproduced ignored binding digests for
Telegram and Discord on `c64bd36ca6728ca3cfb55e89aefaeb6697ecf9b7`.
Independent fresh runs export that exact production source to disposable runtime
copies and fail on forged-binding with the current fixture. The working checkout
is never reset; the fixed source passes those same assertions.

Both paths now capture and validate the independent owner route before sending
and recheck it before subsequent native writes. Telegram receives the same private
current-policy context in the service as the other native adapters, preserves
shared nested-delivery accounting and denies owner changes before chunks or
Markdown fallback. Accepted partial delivery remains uncertain, not retryable.
Discord checks both the native request boundary and each actual HTTP attempt,
including an SDK-internal nonce retry. Owner withdrawal prevents subsequent
chunks, reply fallback and nonce retry without losing ambiguity from an earlier
500 response. Existing thread/guild/nonce and receipt checks remain enforced.

Fifty-nine actual native send/outbox cases pass: Telegram 16, Discord 23, Slack
20. Each includes a valid current binding without read permission that must emit
no reply. Telegram native polling/durable offset recovery and Discord ingress/
history regression also pass. Full/minimal suites each pass 1202 tests and two
existing skips with the unchanged local backup-file exclusion. Fifty-five actual
root/UID/socket/recovery cases pass; atomic root-policy replacement is tested
under the gateway UID for all three platforms, with owner secrets unreadable.
No CI skips or mock replacements were added.

Exact current/baseline source hashes, failed isolated reproductions and passing
contracts are in
`docs/evidence/2026-10-26/telegram-discord-current-authority-validation.json`.
These local tests do not establish external delivery, real account access,
installed service/boot or release acceptance. Home Assistant remains prepared;
there are still six public text-gateway paths.

### Private Slack/Discord SDK redirect refusal (2026-10-26)

New actual SDK cases failed on `4750a5d993385d9367057105fb962f4511163fb3`:
Slack and Discord followed HTTP 307 to an unapproved local endpoint and accepted
its otherwise valid-looking message receipt as delivered. Both fixtures expected
uncertain delivery and no follow-up request. No external message was sent.

The private Slack client subclass now forces `allow_redirects=False` in its real
SDK `_request` path, preserving per-copy token/session semantics. The private
Discord request boundary also disables redirects before invoking the actual SDK.
All native HTTP encoding, parsing, nonce checks and current owner-grant checks
remain active. Redirect responses remain uncertain; they never authorize an
automatic resend or a new recipient. The frozen Telegram HTTP client already
refused the redirect; an actual SDK regression case now preserves that contract.

Sixty-two native delivery/outbox cases pass: Telegram 17, Discord 24, Slack 21,
with zero requests observed at the redirect target. Native Telegram polling and
Discord/Slack ingress/history regression pass. Full/minimal suites each pass
1202 tests with two existing skips and the unchanged local backup-file exclusion.
All 55 actual root/UID/socket/recovery cases pass; no CI skips were added.
Source hashes and individual receipts are recorded in
`docs/evidence/2026-10-26/private-gateway-sdk-no-redirect-validation.json`.
These loopback protocol checks do not establish live account/TLS/external
delivery, installed boot or final artifact acceptance.

### Public Home Assistant text setup and owner recovery (2026-10-26)

The public gateway policy, private runtime factory, graphical owner management
and `haos-owner gateway setup home homeassistant` now share the reviewed
Home Assistant path. This brings the public text paths to seven: Telegram,
Discord, Slack, Mattermost, Matrix, ntfy and Home Assistant. This is not completion
of the 22-adapter requirement or media/voice support.

The private long-lived token and canonical HTTPS instance URL are validated
before graphical configuration stops the gateway. The actual pinned adapter runs
with a separate private HOME, a kernel lease, authenticated continuous WebSocket
subscription and durable SQLite admission. Pairing requires an exact authenticated
32-character user ID and exact entity ID; no scope/thread wildcard or synthetic
human identity is accepted. Explicit `system` routes additionally require
`--homeassistant-trust-system`: this authorizes all system/automation producers
of that exact entity, not a verified person. Unknown human users remain denied.
Only `create` and `read` apply; device tools and chat command rights are absent.

Replies use native persistent notifications and are visible to **every user of
the Home Assistant instance**. A read grant therefore requires unchecked-by-default
GUI consent or `--homeassistant-shared-notifications` on pairing. Sending retains
the existing exact-route/outbox binding, authenticated receipt witness and
conservative uncertain-delivery recovery. This is not private per-user messaging.

The GUI provides private credential entry, exact pairing, status and explicit
`retry-homeassistant-auth` recovery. This offline owner action permits a fresh
real authentication attempt; it never sends, grants a route, clears a future
rate-limit deadline or repairs an unresolved delivery automatically. Re-pairing
with the same account retains authentication refusal and throttling across new
owner generations. The private legacy status schema migrates additively without
removing earlier rows, receipts or gaps. Real UID/NSS/chroot tests exercise the
actual recovery executable with both existing and absent journals.

Stock Home Assistant history omits the original authenticated event context.
Reconnecting therefore cannot authenticate unseen events from the outage;
`gap_since` stays visible. Retained local events can be replayed subject to current
HAOS authorization. No remote history, account, external notification, installed
boot, hardware or final artifact acceptance is claimed by these local tests.

### Prepared IRC account admission (2026-10-26)

The pinned IRC codec strips the prefix down to a nickname and does not parse
IRCv3 message tags. A nickname allowlist cannot establish an authenticated
account: another person can reuse a nick. The new prepared boundary requires a
server account tag, original server timestamp, stable server message ID and an
exact owner account/channel/server grant before durable admission. Client-only
account tags, duplicate/escaped identity tags, hostmasks as identities, channel
wildcards, direct messages and unaddressed channel chatter are refused. Native
message decoding still runs through the actual pinned adapter after the private
journal commit; its synthetic nick/time/ID are replaced only within that retained
context. Reopened local replay checks current grants and cannot repeat admission.

`probe_irc_ingress.py` now runs in runtime build and provider-contract CI. Its 29
actual codec/SQLite cases supply capability metadata locally; they do **not**
prove a TLS connection or actual server capability negotiation. IRC stays rejected
by public GatewayPolicy and has no public setup. TLS/account-capability negotiation,
reconnect, delivery/recovery and GUI remain required before enabling it. The
public text-gateway count remains seven; no live IRC/account test was performed.

### Prepared IRC TLS and capability subscription (2026-10-26)

The prepared transport opens bounded, hostname-verified TLS (system CA trust,
minimum TLS 1.2), negotiates account-tag/server-time/message-tags before accepting
registration, and waits for the exact channel join before admitting input. The
actual pinned IRC codec decodes only retained account-authorized messages.
Unpaired accounts, missing capabilities, malformed/incomplete/oversized frames,
registration before capability acknowledgement and changed subscription identity
fail closed. Idle reads recheck owner authority; withdrawal, local identity
mutation, capability removal, kick/part/nick changes and EOF close the socket.
The separately reviewed raw inbox remains the replay authority.

Thirty real local TLS/IRC/SQLite cases include a disposable CA and hostname,
wrong-hostname and untrusted-CA rejection, multiline capability negotiation,
PING/PONG, a private server PASS, eight protocol/framing refusal categories and
seven live private-identity mutation checks. Only fixture destinations and the
disposable trust anchor change. No certificate verification is disabled.
Build and provider CI now require the transport probe. Minimal and frozen full
Python 3.11 suites each pass 1228 tests with two existing skips.

Native sends, standalone fallbacks and application writes remain blocked pending
reviewed outbox integration. NickServ passwords are explicitly refused rather
than disclosed to an unauthenticated nickname; a reviewed service/SASL auth path
is still required. Persistent profile/reconnect/rate-limit status, delivery,
public owner setup and GUI remain unfinished, so IRC is not an eighth public
text gateway. These are local TLS/codec contracts, not an external IRC account,
service-authentication, installed or release acceptance.

### Prepared IRC SASL account authentication (2026-10-26)

Optional paired `sasl_username`/`sasl_password` credentials now negotiate SASL
PLAIN strictly over the verified TLS transport. The capability offer must include
SASL and, when advertised, PLAIN. An expected challenge precedes payload delivery;
400-character base64 chunks and the required terminal `+` for exact multiples
follow IRCv3 framing. Registration waits for both an exact expected account in
numeric 900 and SASL completion 903. Unexpected challenges, a different account,
missing account confirmation, unavailable mechanisms and premature registration
never reach JOIN or input admission. Authentication refusal and live logout close
the connection and latch refusal for that boundary, preventing implicit retries.
NickServ nickname password delivery stays disabled; SASL does not authorize any
new incoming account or expose a public gateway.

The actual local TLS transport probe expands from 30 to 41 cases, retaining all
earlier assertions and adding positive short/chunked/exact-boundary authentication,
negative protocol/account cases and live logout. Private payloads are redacted in
the fixture's command journal. Full and minimal Python 3.11 suites each pass 1237
tests with two existing skips. Durable profile/reconnect/auth-recheck status,
outbox witnesses/recovery and public owner setup remain unfinished. No external
IRC service/account or installed acceptance is inferred from these fixtures.

### Prepared IRC tagged server controls (2026-10-26)

IRCv3 server-time may tag registration, JOIN and PING as well as application
messages. A new real TLS fixture fails at the positive tagged-control handshake
against isolated exact `322eae6` transport source (timeout); the corrected boundary
strips a validated, duplicate-free tag envelope before the actual pinned parser
handles controls. Account admission continues to require its separate original
authenticated tags. Password/access refusals 464/465 now latch authentication
refusal rather than entering generic reconnect. All prior assertions remain;
the transport probe now passes 44 cases. Both runtime suites pass 1237 tests/two
existing skips. No public IRC enablement or external acceptance is implied.

### Prepared IRC private profile and persistent recovery (2026-10-26)

The actual registered pinned IRC factory now has a prepared private HOME and
single-link service-owned kernel lease. Continuous TLS input and local durable
replay run independently; the shared supervisor joins both on stop. Bounded
reconnect keeps the original grant and records status/deadlines in the private
native inbox. Server account-access/SASL refusal persists across connect, profile
close and real SQLite reopen. Explicit credential rotation may start a new
account check without deleting earlier refusal rows. Changing owner generation
or bot nickname is not credential rotation and does not bypass account refusal
or throttling. Server 263/439 deferral uses a conservative 60-second delay;
persisted deadlines survive shutdown and re-pairing.

Fourteen actual profile/TLS/SQLite/kernel cases cover duplicate leases, continuous
native input, EOF reconnect, concurrent close, refusal and throttle persistence,
credential rotation, replay of failed local admission on an otherwise idle TLS
connection, supervisor stop, owner revocation and cancellation during a real TLS
handshake. Together with 29 ingress and 44 transport cases, these are 87 prepared
local IRC cases. Both Python 3.11 runtime suites pass 1240 tests/two existing skips.
The gap timestamp remains visible: no remote history mechanism is negotiated and
no unseen outage input is claimed recovered. Prepared owner auth-recheck metadata,
reviewed delivery/receipt/recovery and public CLI/GUI remain required. IRC stays
publicly disabled; these fixtures prove neither external accounts nor installed
boot/release acceptance.

### Prepared IRC private wire-alias redaction (2026-10-26)

The shared credential redactor now includes private IRC server/NickServ/SASL
passwords and the exact SASL base64 payload and 400-character chunks. The SASL
builder and redactor share one canonical chunk encoder; the protocol terminal
`+` is not registered as a secret. A reflected private alias is removed before
native inbox persistence, actual IRC decoding and durable relay admission.
An isolated copy of the exact parent `657f7dd` runtime redactor fails the new
native pre-persistence assertion; current code passes without relaxing it.
Thirty ingress, 44 TLS/transport and 14 private-profile cases pass (88 total),
as do 1244 tests/two existing skips in both Python 3.11 environments. This remains
prepared IRC work: no public enablement, external account or installed acceptance.

### Prepared IRC offline owner authentication recovery (2026-10-26)

Safe owner metadata now includes bounded IRC status/deadline/gap values and hashed
source receipt IDs without raw events or credentials. The prepared auth-recheck
function uses the same fixed-platform, atomic status/audit transaction as Home
Assistant. It clears only authentication refusal for the exact configured
connector, preserves future throttling, gaps, revocation, other connectors and
retained input, and performs no network IO. A fresh private profile performs the
next actual authentication after the explicit decision. Public IRC helper-main,
CLI and GUI are not enabled by this prepared function.

Two new real Root/kernel fixtures exercise gateway UID 65534 and deny agent UID
65533 access to the journal, with both successful audit and actual SQLite-trigger
storage failure/rollback. All 65 gateway authority/control/recovery cases pass.
Twenty-four paired Home Assistant/IRC recovery unit cases pass, and both broad
Python 3.11 environments pass 1256 tests/two existing skips. The native HA profile
regression retains 33 cases; the IRC profile expands to 15, making 89 prepared
IRC ingress/transport/profile cases including earlier 30/44 cases. No unknown
remote outage event, external account, public eighth gateway or installed/release
acceptance is claimed.

### Shared offline outbox readiness (2026-10-26)

The private gateway service previously requested an outbox lease before checking
whether its adapter was connected. Repeated offline polling consumed the five
attempts and could fail a reply without ever sending it. The service now passes
only currently connected connector IDs to the existing peer-authenticated
`gateway.next` method. The controller validates a distinct bounded list of exact
configured names; the mission queue selects only these connectors. Offline
obligations remain pending at attempt zero, survive reopen, and do not block
other connected gateways. Existing empty-parameter callers retain compatibility.
Owner revocation and crashed-send lease expiry still run even with no ready
adapters; readiness never converts a previously started send into a retry.

The new positive ready=[] Unix-socket assertion fails against isolated exact
`8121c3c` controller/engine source, which incorrectly returns a sending obligation.
Current source passes that same real peer-authenticated socket fixture and all
65 authority/control/recovery cases, including malformed selectors and withdrawn
peer authority. Eight new queue cases cover persistence, multiple connectors,
revocation and invalid selection. A real native IRC TLS-profile case continues
through mission persistence, offline polling, reopen and first online lease.
Both Python 3.11 suites pass 1264 tests/two existing skips. This repairs shared
queue behavior, not an external delivery or installed/boot acceptance.

### Prepared IRC native send and correlated server acceptance (2026-10-26)

The prepared sender now runs the actual pinned IRC markdown/UTF-8 chunker and
`send` method behind an exact current owner channel/read/outbox/attempt capability.
Native raw or standalone calls cannot write without that bounded context. Durable
intent precedes socket writes; each native chunk waits for a correlated echo with
matching label, own sender, account when SASL applies, channel, exact text, stable
server ID and original server time. Every next write rechecks current authority.
The SDK's synthetic local millisecond ID is never treated as a server receipt.

Echo-message, labeled-response and batch capabilities must all be negotiated.
A bare ACK is insufficient. Labeled batches require their correct terminal frame;
wrong origin/type/identity, duplicate or missing echoes, incomplete batches and
socket loss remain uncertain. Confirmed attempts reuse their durable receipt
across actual journal reopen. Uncertain attempts are not resent. The actual
mission outbox remains uncertain across reopen until an audited owner decision
explicitly permits a new attempt. Cancellation joins active sends; actual SQLite
intent failure prevents writes and confirmation-storage failure cannot report
success. CTCP/DCC/control injection and unbounded payloads are refused.

The 36 actual local TLS/SDK/SQLite cases cover these positive and negative paths,
SASL account echo matching, native UTF-8 multi-chunk output, revocation between
confirmed chunks, shared dispatcher metadata and actual owner-authorized retry.
The other prepared IRC probes retain 30 ingress, 44 transport and 16 profile cases
(126 total). Both broad Python 3.11 suites pass 1264 tests/two existing skips.
Build/provider CI require the new probe and retain the protocol reference.

**Confirmation limit:** IRCv3 explicitly permits a faked echo for silently blocked
messages, such as spam filtering. This receipt confirms a matching server echo;
it cannot prove fan-out or human receipt. `recipient_receipt_verified` stays false.
The implementation checks the immutable reference at IRCv3 specifications commit
`1b4050eecfd0e2c605c413080b555a41261e8696`; no external code is imported. Public
IRC factory/profile sender wiring, complete recovery metadata and owner CLI/GUI
remain unfinished. IRC is still publicly disabled, and no external message,
account, recipient, installed/boot or release acceptance is claimed.

### Prepared IRC shared factory and profile sender lifecycle (2026-10-26)

The shared factory now accepts IRC only with the exact private parent/connector/
policy/inbox context. Public GatewayPolicy and owner setup still reject IRC.
The registered private profile constructs the reviewed sender only for read
bindings, negotiates its additional capabilities before connection, and owns its
shutdown. Creation-only profiles retain the original incoming capabilities and
no sender. Closing a profile cancels and joins active native sends before closing
the journal/lease, preserving uncertain partial intent without another chunk.

Twenty real profile/TLS/kernel/SQLite cases now pass. The actual registered
factory continues from authenticated input through a real mission outbox, native
send, matching server echo and durable acknowledgment. Scope-less/arbitrary
factory contexts fail before network IO; creation-only and active-shutdown cases
are explicit. Both runtime suites remain 1264 tests/two existing skips. Shared
factory regressions retain HA 33, ntfy 23 and Matrix 23 native profile cases.
Server echo still does not prove recipient delivery; no public eighth gateway,
external account/message or installed/boot acceptance is claimed.

### Actual IRC gateway-UID process death and journal recovery (2026-10-26)

A mandatory disposable-root provider-CI fixture installs public HAOS code,
the exact frozen SDK dependencies and pinned prepared Hermes source with the
normal package installer. It runs the registered private IRC factory as actual
UID 65534 against an actual loopback TLS server using default system CA and
hostname verification, with the disposable CA added only inside that fresh
container. The production connection target is localhost; no socket/UID/TLS
verification function is replaced.

After the server observes the first native frame, the parent sends real SIGKILL
to the still-waiting gateway process. Actual agent UID 65533 cannot read/open its
journal or the private owner canary. A new UID-65534 process reopens the committed
`writing` intent, reacquires the released kernel lease and retains it as uncertain;
it authenticates a new TLS connection but emits no repeated application message.
All three cases pass in the pinned container image with networking disabled.
The fixture rejects execution on installed HAOS or outside its explicit fresh
PID-1 Docker namespace. This is process/UID/TLS/journal evidence, not an installed
HAOS boot, external account/message or recipient-delivery acceptance.

### Prepared IRC owner delivery inspection and receipt migration (2026-10-26)

Native owner inspection now exposes a bounded IRC intent list containing state,
outbox/attempt, hashes, confirmed-chunk count and the local aggregate server-echo
reference. Message text and raw remote IDs are not returned. Recipient receipt
remains explicitly unverified. The journal adds the receipt column without
replacing legacy rows, and cached confirmations fill an older missing reference
without another socket write. Native attempts obey the same maximum five attempts
as the mission outbox. Credential-reflecting server IDs are refused before receipt
storage; native replay/confirmation cannot turn such an ID into observer data.

Thirty-eight real native send/TLS cases pass, including additive legacy migration
and an actual SASL private-alias echo refusal. Both broad Python 3.11 suites pass
1275 tests/two existing skips. All 68 real authority/control/recovery cases pass,
including the three IRC owner outbox decisions under actual ledger UID 65534.
The actual SIGKILL/UID/TLS process fixture retains three cases at the new schema;
IRC/HA profile regressions retain 20/33 cases. IRC is still not publicly enabled,
and these results are not external account/message, recipient or installed/boot
acceptance.

### Prepared IRC canonical channel and exact account identifiers (2026-10-26)

Incoming standard IRC channel case and the bot's own nickname case are now
compared canonically; authenticated account IDs retain their exact server spelling,
including uppercase letters. This does not convert a nickname into an account or
authorize a differently spelled principal. Exact local `&channel` routes use the
actual pinned codec as well. Unknown advertised CASEMAPPING values fail closed.

Native cases now total 136: ingress 32, transport 45, profile 20 and delivery 39.
The new cases distinguish channel case from exact account identity, cover local
channels and reject unsupported server case mapping. Existing broad/root/process
regressions retain 1275 tests/two existing skips in both Python 3.11 environments,
68 actual authority/control/recovery cases and three actual UID/SIGKILL/TLS cases.
Public IRC owner setup remains disabled; no external or installed acceptance is
inferred from these local cases.

### 2026-10-26 — public IRC owner integration

The IRC text path now connects the actual owner CLI and graphical management to
its previously tested private native runtime. Canonical TLS server/channel
credentials bind independent exact-account grants. SASL-less setup needs explicit
owner consent; private fields clear on submission and context changes. The runtime
refuses to connect before pairing. Offline authentication recovery now dispatches
through the public policy under the actual unprivileged gateway UID. The owner
view labels IRC transport/outage state and bounded private outgoing metadata,
including the explicit server-echo/recipient-receipt distinction.

Validation on this change: minimal and complete frozen Python 3.11 runtimes each
passed 1,278 tests with two existing skips and the unchanged local backup-file
exclusion. Actual Tk fixtures passed IRC 10, Home Assistant 11, ntfy 11 and Matrix
7 cases at both 1280x800 and 640x480 (system Python 3.13.5). Four native IRC
probes use the public GatewayPolicy and retain all TLS, capability, account,
replay, SASL, private-profile and delivery assertions. Root publication and
recovery probes use actual Unix UIDs and disposable owner-protected files.
No external message, installed owner session or release artifact is claimed.

### 2026-10-26 — prepared LINE signed text admission

LINE remains publicly disabled. A new independent prepared boundary verifies the
exact raw webhook body through the actual pinned LINE HMAC verifier before JSON
processing. It rejects duplicate JSON keys, oversized batches, wrong bot
destinations and events outside the captured timed owner grant. Only exact
signed user/group/room identities and active text messages reach NativeInbox;
unknown senders, missing user identity and media cannot inherit authority.
Single-use reply tokens are omitted from retained payloads and native decoding.
The actual pinned text codec runs only after observable private journal commit;
local dispatch failures retain retry deadlines across SQLite reopen. Withdrawal
blocks pending work. Native listener, dispatch, postback, typing, media and send
entry points remain denied in this prepared profile; no live client is admitted.

The mandatory build and provider-contract workflow run the new actual native
probe (35 cases). Eleven policy/identity cases also run in the minimal suite.
Both frozen Python 3.11 environments passed 1,289 tests with two existing skips
and the unchanged local backup-file exception. This establishes prepared input
contracts only: a verified listener, outbound transport, private service profile,
recovery, CLI/GUI and external account acceptance remain to be implemented.
The public gateway count remains eight text paths.

### 2026-10-26 — prepared LINE fixed-route webhook application

The next prepared layer creates an aiohttp application without opening a socket;
its caller must supply the eventual service binding and trusted TLS ingress.
Only POST `/line/webhook` is exposed, with a 64-KiB limit, bounded read time,
exactly one signature header and fresh independent owner-policy inspection.
Success follows private durable admission; native decoding remains replayable
outside the HTTP request. Storage failures return a generic 503 so the remote
server may redeliver after recovery, without exposing errors or credentials.
No native media, plugin or health routes are inherited.

Thirteen actual loopback HTTP/HMAC/SQLite cases verify observable commit before
200, duplicate delivery, malformed/signature/size rejection, absent auxiliary
routes, a real SQLite trigger-induced storage fault and successful redelivery
after removing that fault, plus immediate withdrawal of the owner grant.
Build and CI run the listener probe. This does not prove external TLS reachability,
a public listener deployment or a full LINE integration. LINE stays disabled.

### 2026-10-26 — prepared LINE reflected capability redaction

Before retention, the LINE boundary now removes known channel-secret,
channel-access-token and event reply-token values reflected inside message text.
The retained event and approved envelope use identical redacted text, so actual
native decoding cannot reintroduce those capabilities. The single-use raw reply
field remains omitted entirely. The updated native probe passes 36 cases; the
same unmodified probe against `cb8dec6` fails specifically because reflected
private values remain in its payload. Thirteen actual loopback listener cases
still pass. Both full frozen and minimal Python 3.11 suites pass 1,289 tests with
two existing skips and the unchanged local backup-file exception.

### 2026-10-26 — prepared native LINE push receipts and write intent

The actual pinned `LineAdapter.send`, markdown/text chunker and `_LineClient.push`
now run behind a prepared HAOS publisher. Its only allowed wire operation is the
fixed LINE push endpoint with the approved exact chat, native payload and private
bearer token. Current owner `read` authority is checked before invocation and
again at the native HTTP boundary. Native reply-token and pending postback
capabilities are refused, preventing automatic reply-to-push fallback.

A bounded private SQLite intent is committed before the native POST. The same
outbox ID/attempt cannot inherit changed content or grants. Confirmed attempts
return their retained receipt without another write; writing/uncertain attempts
never resend automatically, including after reopen. Failure to retain a server
confirmation leaves uncertainty. Only an HTTP 200 with a canonical remote request
ID and a complete, distinct set of remote message IDs confirms server acceptance;
the native adapter's `None` result ID is not promoted to a receipt. Quote tokens
and vendor error bodies are not exposed. This is not proof of recipient receipt.

Production uses default verified TLS, no proxy inheritance, redirects or transport
retries. Twenty-five real native/loopback HTTP/TLS/SQLite cases cover server
receipts, refusal/rate-limit/error handling, missing/invalid proofs, redirect and
connection abort, commit/confirmation faults, cancellation after HTTP write,
SQLite reopen, raw-client denial, revocation, unknown CA and wrong hostname.
A disposable trusted CA succeeds with hostname verification enabled. Build and
CI run this probe. Both Python 3.11 regression environments pass 1,289 tests with
two existing skips and the unchanged local backup-file exception.

This prepared path admits one native push (up to five bubbles). Native ellipsis
truncation or a bubble exceeding LINE's UTF-16 limit is rejected before dispatch.
It is not yet connected to a public LINE service profile, outbox factory or
owner setup/recovery. LINE remains publicly disabled; no external message or
account/installed acceptance is claimed.

### 2026-10-26 — prepared LINE private identity, lease and service profile

The prepared shared factory now requires an exact private LINE context, canonical
channel credentials, bot destination and unprivileged local port. It registers
only the pinned bundled adapter under a private HOME and acquires a real private,
single-link kernel lease. No network is opened at construction. A current timed
owner grant for that bot is required, and changed grants are refused at every
incoming admission rather than waiting for the replay worker.

Before binding, the actual pinned `_LineClient.get_bot_user_id` runs through a
bounded fixed `/v2/bot/info` HTTP boundary with default verified TLS, no redirects,
proxy inheritance or retries. Only the exact bot destination is accepted. Auth
and identity refusal persist across profile/owner-epoch reopen; rate-limit
deadlines survive closure. The prepared profile binds **127.0.0.1 only**. It does
not provision an externally reachable HTTPS reverse proxy or certificate.

The fixed webhook application and persistent replay worker share the private
journal and current owner authority. Creation-only grants create no publisher.
Read-capable profiles cannot send before a verified connected bot identity; their
actual native push path requires exact current Root outbox metadata. Publisher
and replay access are serialized. Disconnect/close joins workers and releases
listener, sessions and kernel lease. Revocation stops the idle listener.

Twenty actual native-profile cases include private paths/lease exclusion,
no-pairing refusal, native bot lookup, signed input/RelayInbox replay, the common
factory plus MissionStore/GatewayEngine outbox/native push/server receipt/durable
acknowledgment, offline zero-attempt preservation, grant-epoch changes, retained
local failures, auth/identity/throttle persistence, redirect refusal and actual
listener port conflict/recovery. They run in build and CI. Native ingress 36,
listener 13 and delivery 25 regressions pass. Full frozen and minimal Python 3.11
suites each pass 1,307 tests with two existing skips and the unchanged local
backup-file exception; 71 actual Root/UID/credential/recovery regressions pass.
These are separate fixture and kernel tests, not an installed LINE acceptance.

Public policy still excludes LINE. Public TLS ingress/certificates, owner
CLI/GUI, authentication/delivery recovery, media/voice and external account
acceptance remain incomplete; the public text-gateway count stays eight.

### 2026-10-26 — prepared LINE offline authentication/identity recheck

The shared private recovery transaction now permits a prepared LINE owner recheck
of authentication and bot-identity refusals. It records the owner UID, current
policy digest and note digest atomically with clearing those blocks. It performs
no network request. Future deadlines, rate-limited/revoked rows and retained
native inputs remain unchanged. Audit failure rolls back every status change.
Public LINE policy, CLI and recovery dispatch remain disabled.

The actual native-profile probe now passes 24 cases, including offline decisions
followed by fresh native bot verification; a rate-limited profile remains blocked
at its original deadline. Two additional real-UID fixture cases run both gateway
UID 65534 and agent UID 65533 against private gateway journals and a root-only
canary, including an actual SQLite audit trigger failure. Agent UID cannot open
the journal; gateway UID cannot read owner data. These use the minimal runtime
without optional Hermes imports. All 73 Root/UID/credential/recovery tests pass.
Home Assistant (33) and IRC (20) actual native-profile regressions pass after the
shared transaction change. Full frozen and minimal Python 3.11 suites each pass
1,307 tests with two existing skips and the unchanged local backup-file exception.
No external account, installed session, public TLS ingress or release is accepted.

### 2026-10-26 — prepared LINE bounded owner inspection and actual Tk status

Private owner inspection now accepts only LINE's reviewed hashed ingress IDs and
bounded profile/intent metadata. Unknown platforms, raw IDs, malformed receipts,
invalid attempts/states/timestamps and conflicting confirmed/uncertain proof
fields are refused. Profile/output records expose no message text, raw server IDs,
tokens, credential-scope hashes or publisher fingerprints. The existing ingress
summary retains its bounded payload digest. Retained server-acceptance
proofs explicitly carry `recipient_receipt_verified: false`.

The actual owner recovery view distinguishes local listener readiness from
unverified public HTTPS reachability, authentication versus bot-identity refusal,
persisted rate deadlines, revocation and writing/confirmed/uncertain push intents.
LINE remains absent from public setup choices. Seven actual Tk/private-SQLite
cases pass at 1280x800 and 640x480 (system Python 3.13.5); the GUI workflow runs
both. Existing IRC 10, Home Assistant 11, ntfy 11 and Matrix 7 GUI cases also pass
at both resolutions. This is a backend-handoff fixture, not an installed owner
session. Root tests separately inspect these records under the actual gateway
UID without importing optional Hermes SDKs.

Full frozen and minimal Python 3.11 suites each pass 1,321 tests with two existing
skips and the unchanged local backup-file exception. All 73 actual Root/UID/
credential/recovery cases pass. The new Root inspection case first exposed the
missing LINE ingress-ID branch; the fix adds only LINE's canonical SHA-256 IDs,
with explicit tests that unknown plugins and raw message IDs stay refused.
Public TLS ingress/owner setup, remaining delivery recovery and media/voice are
still incomplete. No public LINE, external account or installed acceptance.

### 2026-10-26 — prepared LINE verified HTTPS listener material

An optional owner TLS profile now starts the actual fixed webhook application as
HTTPS. Canonical public URLs use the fixed `/line/webhook` path and standard
HTTPS port, with no embedded credentials, query or fragment. Literal IP URLs
are refused. An explicit boolean consent is required for wildcard public
binding; legacy prepared profiles remain loopback-only without TLS.

Before listener admission, the supplied PEM chain is verified against the local
system trust store at the current time for the exact DNS name, and the private
key must match. Weak/invalid/mismatched keys, untrusted/expired chains and unsafe
listener choices are refused. Private TLS files are installed mode 0600 and
single-link through atomic creation in the private profile, with no overwrite
of conflicting retained files. Existing owner material stays available for
recovery. The server requires TLS 1.2 or newer. Neither local trust nor successful
binding proves remote LINE reachability or LINE's public trust acceptance.

Seventeen actual X.509/TLS/native-profile cases pass, including verified HTTPS
through signature validation, durable RelayInbox and the pinned native codec,
wrong hostname/issuer/expiry/key, consent/path validation and retained-file
conflicts. Runtime build and CI run the new probe. LINE profile 24, input 36,
listener 13 and push 25 regressions pass. Seven actual recovery GUI cases pass
at both 1280x800 and 640x480 with distinct TLS-ready/unverified-external wording.
Full frozen and minimal Python 3.11 suites each pass 1,321 tests with two existing
skips and the unchanged local backup-file exception. Public LINE setup and full
gateway acceptance remain pending; no external DNS/router/account test claimed.

### 2026-10-26 — IRC gateway software closure

IRC now includes owner-managed private `+k` channel keys, exact JOIN parameter
encoding (including leading colon), automatic private credential/wire-alias
redaction at profile construction, and explicit refusal of non-native binary
file/voice transfer methods. Those methods cannot emit misleading fallback
success or private host paths. CLI port errors no longer echo arbitrary pasted
input. GUI catalogue availability now follows the actual authorized transport
set, including IRC and Home Assistant.

Bounded diagnostic codes persist in an additive IRC profile column, survive
close and appear through private owner inspection and GUI. They distinguish
nickname, channel key/invite/ban/full/not-found/forwarding, capability and network/
TLS problems without vendor text. Legacy journals remain readable. The runtime
checks its actual service UID/GID and supplementary groups before credential
loading; actual UID/NSS tests exercise valid/invalid identities and groups.

The comprehensive scope/operation/acceptance matrix is `docs/GATEWAY-IRC.md`.
Local validation passes both Python 3.11 environments (1,330 tests, two existing
skips, unchanged local backup-file exception), 151 native IRC cases (37 input,
54 transport, 21 profile, 39 delivery), 12 IRC GUI cases at both resolutions,
all existing gateway GUI regressions and both complete embedded GUI workflow
programs. Actual Root/UID/credential/recovery coverage is 83 cases, plus three
actual installed-code/UID/TLS/SIGKILL process cases using public GatewayPolicy.
The exact implementation commit still requires green CI; live server/account,
recipient and installed-machine acceptance is separate. No final HAOS release.

The final runtime identity guard also requires real, effective and saved UID/GID
to match the service identity. Four additional actual setresuid/setresgid cases
reject launchers retaining real or saved root IDs before credentials or SDK
imports. They pass in the isolated minimal-runtime kernel fixture.
### 2026-10-27 — public LINE owner text setup

The earlier prepared-only LINE state is superseded by actual owner GUI/CLI
setup, private bounded PEM import, verified HTTPS listener parameters, explicit
public-bind consent and exact sender/chat grants scoped to the saved bot ID.
The regular GatewayPolicy, credential publication, runtime factory, delivery
metadata and offline authentication/delivery recovery now admit LINE through
the same independent HAOS boundaries. System Python explicitly depends on
`python3-cryptography` for local PEM/certificate validation; provider SDKs are
not imported in the root GUI.

Native LINE probes now use the regular policy instead of a prepared-policy
exception. The TLS probe also checks an expired profile remains inspectable,
refuses activation before any HTTP and reports a retained safe diagnostic.
Disposable actual-root owner lifecycle and both-resolution Tk setup/recovery
checks are required in CI. See [operation and evidence boundaries](GATEWAY-LINE.md)
and `docs/evidence/2026-10-27/line-owner-setup-validation.json`.

There are now nine publicly configurable **text paths**, not nine complete
platform acceptances. Media/voice require the still-missing shared media broker;
external LINE accounts, DNS/router/firewall reachability, recipients and installed
OS acceptance remain separate. No release artifact or live delivery is claimed.

### 2026-10-27 — private mission attachment transport core

The controller now persists bounded, grant/message/epoch-bound media chunks and
atomically associates ready IDs with a new gateway mission. Revocation, changed
bytes, altered IDs, incomplete uploads and damaged retained data fail closed.
Existing text missions read no optional gateway policy. Actual pinned image-byte
and file-data-URL RPCs receive only bytes and fixed names, then document refs join
the mission prompt. [Media transport scope](GATEWAY-MEDIA.md) records bounds and
remaining integration: public LINE download/relay, GUI opt-in, retention controls,
audio/voice and outbound media remain open at this backend checkpoint.

The new real-backend probe transfers an actual decoded PNG and a byte-identical
8 MiB document without a model turn. A stdlib-only disposable process probe
checks real separate UIDs, SO_PEERCRED, private SQLite and owner epoch changes;
both are required in provider CI, the native RPC probe also in image build.

### 2026-10-27 — LINE incoming attachments and isolated speech core

The earlier media-core checkpoint's open public input/GUI/retention work is now
superseded by the actual [LINE image/document path](GATEWAY-LINE.md) and
[separate owner storage controls](GATEWAY-MEDIA.md). Controller operations use
its fixed private `haos-control` recovery helper; gateway cache operations use
the actual gateway UID. Current sender grants/nonterminal missions cannot be
silently purged, and explicit decisions retain audit/tombstones. Source-bound
receipts record each increment, including 1399 ordinary tests and 87 actual
root/UID/recovery cases at `e2e161d`; that exact source has six green CI runs.

The next [speech increment](GATEWAY-SPEECH.md) adds the frozen upstream `voice`
extra, bounded local decoding, actual Hermes local STT and a separate offline
socket-activated identity. Native and real-UID probes are mandatory. It does
not yet open LINE audio admission or claim owner GUI/model activation, outbound
media, live accounts, installed boot or release acceptance.

### 2026-10-27 — LINE incoming voice connected to private mission transcription

Owner model/service setup is now available through the actual physical GUI and
`speech status/enable/disable` console actions, independently from sender grants.
The LINE pairing GUI/CLI has a separate `allow_voice` consent requiring create
permission and verified local setup. Existing media grants do not include voice.
The pinned native audio codec and verified content client feed private media
uploads; the controller invokes the isolated STT service, caches a checked
source/model-bound receipt and sends recognized text, never raw audio, to the
agent. Current grants/cancellation/deadlines are checked while waiting and before
dispatch. Corruption or refusal cannot silently produce a text-only fallback.
See [speech operation, tests and limits](GATEWAY-SPEECH.md). Video and outbound
media remain open; no external LINE account, LLM inference, installed/HP or
release acceptance is claimed by the local composition/kernel probes.


### 2026-10-28 — SMS/Twilio owner setup, MMS and recovery connected

The actual pinned SMS adapter now has an independent public HAOS setup path,
exact timed E.164/account-number grants, private account/message/media reads,
verified shared HTTPS ingress, durable decoding and limited controller media
exports. Incoming audio uses actual local STT without raw agent attachments.
Outgoing supported MMS uses native formatter/form/sender; other files use
revocable HTTPS links. Private API catch-up has persisted bounded pagination,
source/grant checks, distinct status and explicit unsupported-content receipts.
Owner CLI/GUI, finite recovery, Root publication and real UID/SIGKILL tests are
connected. Source-bound evidence accompanies the increment; see [SMS operation
and limits](GATEWAY-SMS.md). Ten public text paths do not establish ten fully
accepted gateways or all 22 integrations. Account/carrier/handset, public network,
installed system and release acceptance remain separate.
