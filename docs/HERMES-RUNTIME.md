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
