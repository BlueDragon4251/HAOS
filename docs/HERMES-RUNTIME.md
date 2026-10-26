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
