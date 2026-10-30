# Google Chat — public path under software acceptance

Google Chat now has a dedicated graphical account/pairing page, Owner CLI,
matched Root publication and a connection to the common gateway service. The
accepted software count remains 15/22 while the remaining management/recovery
checks and source-consistent acceptance are completed. Registry/GUI availability
alone does not count as a completed integration. No installed-systemd or live
Google Workspace acceptance is claimed. Sections below retain historical
checkpoint evidence; their results apply to their recorded source revisions.

## Implemented private building blocks

A dedicated inline service-account JSON binds the exact project, service email,
expected bot `users/<numeric-id>` and official Google auth/token/certificate
endpoints. Ambient ADC, arbitrary credential paths and token endpoints cannot
be selected by this prepared schema. Pub/Sub mode selects an explicit same-project
pull subscription; HTTPS callback mode requires explicit listener/TLS material,
an exact callback-URL or numeric project-number audience, an unprivileged
listener port and independently expected caller service account.

Independent grants use immutable user, space and optional same-space thread
resources, an account scope and fresh grant epoch. An email/display alias is
never an authorization identity. Mention and incoming file/voice/video/outgoing
file rights remain separate. Google dotted message resource IDs are supported;
path aliases, cross-space resources, pre-grant messages, automated senders and
unknown peers fail before native decoding or attachment work.

The actual pinned Hermes native message builder is exercised for native Chat
and Workspace Add-ons envelopes, group messages and DMs. Its mutable email ID
and DM thread-count heuristic cannot replace the approved sender/thread. The
Google SDK creates the actual service-account RSA assertion with exact bot and
Pub/Sub scopes. This is a local ephemeral-key test, not a real Google token.

The callback-token verifier uses the actual Google SDK for signature, audience,
issuer and time validation, with exact verified caller email checks. Its private
certificate transport has fixed official URL, timeout/body/cache bounds, refuses
redirects and JWK mode (which would create another SDK fetcher), and never
returns or persists a bearer token. Local certificate fixtures are explicit.

FULL SQLite original custody commits before HTTP success or the actual Google
Pub/Sub SDK's ACK queue operation. Replay retains the first original across
semantically identical native/Add-ons envelopes. Changed content/account/grant,
damaged originals and conflicting parent receipts fail closed. Unknown or
malformed Pub/Sub sources need a durable hash-only refusal audit before ACK;
failed original or refusal commits produce NACK. A dedicated real-UID SDK pull transport now uses fixed TLS gRPC authority,
bounded message/RPC sizes and deadlines without SDK retries or emulator/ADC
selection. Its SQL work stays on the owning asyncio thread. Actual SDK client
and local TLS gRPC server checks exercise ACK/NACK, reopen, authentication/
transport failures and publication withdrawal. Real Google service-account
OAuth and the remote subscription remain separate live requirements.

Prepared text writes use the real native `send` formatter and actual Google API
discovery client. FULL write intent precedes the first HTTP byte; stable client
and request IDs bind each operation. Exact threads use `REPLY_MESSAGE_OR_FAIL`,
preventing native fallback into a newly created thread. Per-client HTTP sends
once, bounds responses and does not redirect; actual SDK-generated bearer
values enter the shared private redactor before wire I/O and native error/log
handling; this also prevents httplib2's
otherwise implicit POST resend after a dropped response. A begun/unclear write
can only reconcile with a read of its exact client ID. A 404 is not proof of
non-delivery. Confirmed operations return their retained receipt without HTTP;
changed bodies, routes or revoked grants cannot reuse them. These are private
primitives; controller outbox authority still needs to be connected by the
production profile.

The fixed HTTPS callback application also runs under the actual private UID,
validates trusted TLS material and native Google RSA tokens, retains source or
hash-only refusal before HTTP success, refuses duplicate Authorization headers,
and returns 503 on failed source commits. Its real TLS fixture uses raw TLS
framing for the duplicate-header case because the ordinary test client
normalizes those duplicates before transmission. Publication replacement
prevents subsequent admission. These are receiver-process checks, not a
complete production daemon or remote Google callback acceptance.

The retained original now also feeds the actual native codec and a guarded
cooperative-MRO admission into FULL native and parent-relay queues. A source
ContextVar prevents unretained native events from using that admission. Native
projection hashes, current grant/account and original checksums are checked
again at dispatch. Actual-UID reopen tests keep one parent record, including a
real SQL failure between parent commit and the source receipt. This proves the
local relay handoff, not a root-controller mission or live inference.

## Remaining acceptance

- Finish native account/status management review and the remaining acceptance
  checks. Original-identity restoration, known-identity token/quarantine/output
  cleanup and global unassociated output cleanup are implemented below.
- Finish source-consistent public-path validation and account/status management
  review. Actual production-loop tests now cover both transports, Root policy,
  separate controller Unix IPC, reconnect, replay and withdrawal.
- Installed systemd/OS acceptance remains part of the system artifact phase.
- Full source-consistent regression, kernel/process/GUI/build gates for that
  public activation. Live Google account/consent/delivery acceptance stays
  separate from the local SDK fixtures.

## Public account, policy and service path

Open **Gateways → Google Chat: Konto einrichten und exakte Absender freigeben**.
Save a dedicated private service-account JSON and the expected numeric bot
resource. Existing credentials can be reused only by an explicit choice; private
values are not returned to the GUI. Account/key changes withdraw old grants.
The same stable app identity cannot belong to two connectors. Configuration and
credentials use the existing atomic Root publication/recovery mechanism.

Pub/Sub requires an explicit same-project pull subscription and separate Owner
trust in **all** authorized topic publishers, including inherited IAM grants.
The pinned Hermes setup documents Google's publisher principal
`chat-api-push@system.gserviceaccount.com`. Give the dedicated HAOS service
account Subscriber access to the subscription. Independently inspect effective
topic IAM: an authenticated pull connection does not authenticate each original
publisher or prevent another trusted publisher from asserting sender IDs. HAOS
does not claim an automatic effective IAM audit. Without explicit consent the
public publication is refused. Unknown senders still never receive HAOS rights.

HTTPS mode uses the exact public `/google-chat` URL, trusted matching certificate
chain and private key from Owner-private PEM files, explicit listener address
and consent, an unprivileged local port, exact audience and expected Google
caller account. Configure the Google Chat app and network/proxy separately;
HAOS does not silently open router ports. TLS/key validation and signed Google
caller verification are independent of HAOS sender grants.

Pair an exact `users/<numeric-id>` with a `spaces/<id>` and same-space thread.
An empty thread alone does not approve other threads. Whole-space thread access
is a separate choice and cannot overlap a specific-thread grant for the same
sender/app/space. Mission rights, mentions, files/images, voice, video and result
file export are separate decisions. Voice requires the configured local speech
service; file export additionally needs the stable user's OAuth delegation.
Known saved accounts, scopes and flags are displayed without credentials.
Use the same page's OAuth/source/reply/file recovery controls, or the historical
page after account removal. Service start/stop, status, connector removal and
grant withdrawal remain reachable through the common gateway administration.

CLI setup is `haos-owner gateway setup CONNECTOR google_chat`; private JSON uses
masked local input. Pairing uses the common `gateway pair` command, including
`--thread` or explicit `--all-threads` and separate media flags. No setup action
sends a test chat message. The common policy now permits at most 32 connectors
and 512 bindings, preserving a finite bound while allowing all 22 platforms.

The common service creates the private Google profile, registers the guarded
native ingress, forwards through the actual controller socket and prepares
Root-bound output before sending. Google output accepts a validated public
policy witness; mutating or relabelling an already constructed policy fails.
The prepared subclass remains available for historical probes. File/checksum,
source, exact thread, credential epoch and current-grant checks remain intact.
The frozen build includes `google-chat` plus native codec, RSA token, custody
and bounded SDK/HTTP text probes; no dependency versions were upgraded.

The production-loop namespace fixture uses actual Root publication, actual
gateway/controller UIDs and the installed controller's required supplementary
gateway group. A Root-owned named-UID kernel ACL grants only the gateway read
access to fixture credentials: the controller cannot read them, and the gateway
cannot write or chmod them. This models service-scoped access without claiming
an installed systemd credential mount. Google HTTP/certificate/gRPC endpoints
are explicit local fixtures. Reconnect is handled by the real `maintain` loop;
replay has two unique sources/replies. A local completion-event fixture exercises
actual manifest RPC/output projection and refuses unapproved file export without
leaking the agent path. Atomic Root withdrawal stops the actual `serve` task.
None of these checks constitutes Google entitlement, external delivery or real
agent inference.

## Private lifecycle and reply checkpoint

Explicit whole-space thread consent is now a separate `all_threads` boolean;
it cannot overlap a specific-thread grant for the same sender/account/space.
Empty thread selection alone does not authorize other threads. Real controller
component tests preserve each incoming thread and reply anchor in distinct
mission/query routes. Pause/resume use the existing independent mission rights.

The prepared private profile holds an actual kernel identity lease, validates
native service-account credentials and the expected own bot membership before
readiness, owns an authenticated HTTPS listener or bounded Pub/Sub client, and
uses persistent originals, native and parent-relay queues. SDK account and
callback-token work stays in the gateway identity. Its isolated Pub/Sub metadata
plugin uses actual Google signing with bounded refresh requests, fresh policy
checks and credential redaction before emitting bearer metadata. No ambient ADC,
emulator, default unbounded refresh client or global SDK replacement is used.

Controller event hashes and a matching original/native/parent receipt guard
native text replies. Per-chunk client/request IDs, exact thread context and FULL
intents precede writes; confirmed replay has no wire operation and an unclear
write can only reconcile its exact client ID. The complete private HTTPS profile
fixture exercises real SDK RSA token exchange, own-bot lookup, callback receive,
controller-component outbox, native TLS reply, reconnect and immediate listener
shutdown on publication withdrawal. Its controller component runs in the
fixture gateway process; this is not root Unix-socket/production-daemon acceptance.

Authentication failures stay blocked across close/reopen until owner recovery.
HTTP Retry-After and actual gRPC RetryInfo produce persistent account deadlines.
Disconnect, close, unrelated status updates and same-account key rotation cannot
shorten them. Token-endpoint 429/5xx is surfaced before google-auth's internal
retry loop, so the private lifecycle controls recovery. Token success responses
are validated and private values enter the shared redactor before SDK parsing.

Media/per-user OAuth, inspected owner recovery/provisioning and real GUI,
installed runtime activation and full root-controller daemon acceptance remain
open. These private lifecycle checks do not change the public count of 15/22.

Current private lifecycle evidence:
[profile and exact-thread reply validation](evidence/2026-10-30/google-chat-private-profile-validation.json).
Five real-UID profile scenarios cover the connected loop, persisted HTTP401
auth block, HTTP429 account wait across close/reopen/key rotation, token-endpoint
429 without hidden SDK retry, and outgoing authentication failure stopping the
listener. All use explicit local TLS/OAuth/Google-service fixture boundaries.
Prior source CI is separately recorded in
[6ee96ff results](evidence/2026-10-30/google-chat-private-receive-ci-status.json);
those results do not establish later source revisions.

## Prepared inspected recovery contracts

The private recovery module returns bounded metadata and byte hashes for retained
originals and controller reply groups. It never returns message bodies, proof
payloads, keys or tokens. Disposing an original requires withdrawal/change of its
exact grant, a matching inspected snapshot, explicit Owner confirmation and a
FULL-journal audit. Payload-bearing proof is compacted with the original; replay
tombstones remain. This does not assert erasure of backups, other copies or WAL.
Authentication recheck clears only the selected current account's sticky block;
it preserves both status and account rate deadlines and performs no network I/O.

An uncertain reply part requires its own exact group snapshot and independent
Owner confirmation of non-delivery. Its audited approval releases one attempt,
with a maximum of four approvals. Confirmed sibling parts cannot be released.
Replaying an earlier Owner decision never rearms a consumed approval. The real
SDK first GETs the stable client ID even after approval: late acceptance closes
the audit without another POST. Only approval plus GET404 permits a new POST,
using the original client/request IDs and exact retained bytes. Consumption and
its audit commit before that POST; disconnect and audit failure do not silently
rearm it. GET404 alone continues to mean unknown delivery.

These are prepared private contracts, not a completed Owner GUI/backend or
production-daemon integration. They do not change the 15/22 public count.

## Prepared Owner recovery handoff and controls

The prepared Root backend stops the gateway service, checks its inactive state,
loads a matched Root-owned policy/private credential publication and starts one
fixed installed Python 3.11 worker with `-E -s`, the actual gateway UID/GID and no
supplementary groups. The worker requires its live Root parent (PID1 is refused),
sets parent-death SIGKILL, NoNewPrivs and resource/time bounds, then checks fresh
publication authority and the real profile flock. It neither imports optional
Google SDKs nor performs account/network operations. Inputs/actions and returned
metadata use closed schemas; only bounded payload-free receipts return to Root.
Root and private journals record the authenticated actor and decision hashes.

Prepared Tk recovery controls call these backend functions for retained-profile
selection, original inspection/disposal, per-part reply approval and auth-block
recheck. Snapshot selection and profile/connector changes invalidate earlier
consent. Late asynchronous results from a different selection are discarded,
and unexpected payload fields are rejected before rendering. These controls are
still outside the public gateway page pending the complete account/media/OAuth
integration; they are not a full Google Chat setup path yet.

The disposable Owner-process fixture uses real Linux identities, parent
credentials, flock, FULL SQLite and kernel parent-death behavior. Only the
systemctl service state is an explicit fixture; this does not prove installed
systemd quiescence or Owner login. Tk desktop/compact fixtures exercise actual
widgets and the wizard's asynchronous queue with explicit privileged backend
fixtures. Neither is a live Google account, installed GUI or release acceptance.

## Prepared incoming media path

Incoming image/document/voice/video declarations now have source-specific private
resource capabilities. The complete service-account message, stable sender,
space/thread, timed create grant and separate media-kind consent are checked
before any download. A download resource must belong to that exact original
message's attachment namespace. `downloadUri` is never fetched, and a Drive
picker reference without downloadable Chat resource fails explicitly rather
than silently losing its attachment. Optional native upload-reference tokens
are kept private, registered for redaction and never used as download authority.
Raw native message payloads do not cross the durable HAOS event boundary.

The private reader uses the actual Google discovery media request and
MediaIoBaseDownload with zero SDK retries, source-bound GET-only HTTP, bounded
responses/buffer/chunks/time and continuous independent grant checks. Response
MIME, contiguous Content-Range and declared total are checked. PNG/JPEG and
MP4/3GP/3G2 declarations must match byte descriptors. No arbitrary URL, fallback
HTTP client or native filesystem cache is used. The actual Hermes message
builder resolves only independently retained copies under its exact asyncio
context; event media references are hashes, not host paths.

First byte identity is journaled before private blob insertion. Replay reuses
existing bytes without another download; a missing first insertion may only
recover the original recorded byte identity. Purged/damaged cache rows are
never restored automatically. Independent aggregate image and private storage
budgets still apply. The prepared real-UID TLS profile fixture passes the PNG
copy through the native attachment codec, FULL cache, actual controller media
begin/chunk/receive/attach methods and verified per-mission bytes. It also checks
resource401 stopping the profile, resource429 persisting account delay, malformed
range refusal and oversized response refusal. Explicit local TLS/OAuth/Google
fixtures do not establish a live account or installed daemon acceptance.

Voice/video kinds have admission/retention contracts; actual Google-specific
local ASR/video decoder process acceptance, native outgoing attachments and
per-user OAuth remain open. The public count remains 15/22.

Source-bound incoming-media evidence:
[incoming media and existing receive/text regression](evidence/2026-10-30/google-chat-private-input-media-validation.json).
Prepared Owner recovery evidence remains separately pinned to its own source:
[Owner handoff and Tk component validation](evidence/2026-10-30/google-chat-private-owner-validation.json).

## Prepared private user OAuth enrollment

Native outbound attachments need the user's Google OAuth delegation. The
prepared enrollment uses the actual frozen Google Flow SDK and pinned Hermes
OAuth scope/redirect contract, with independent HAOS private SQLite PKCE state,
nonce, timed grant and stable Google user resource checks. OpenID is requested
alongside the native `chat.messages.create` scope so a signed stable subject can
be verified instead of trusting a mutable email. Desktop client JSON is bound
to the configured project and fixed Google/loopback endpoints. The callback
must include its original state; a bare code cannot authorize an exchange.

A FULL exchange intent and Owner actor/note hash commit before the first token
request. A begun exchange cannot silently replay after interruption/reopen.
The per-session SDK transport has one bounded token POST, no redirects, ambient
credentials or retry hooks. Actual Google JWT signature/issuer/audience/time
verification precedes the additional exact subject, client and nonce checks.
The SDK result is an opaque private grant, not serialized claim authority.
Successful user credentials and acceptance audit commit together under the
private gateway UID; the completed pending record compacts its PKCE/client
secrets while keeping metadata/audit. Other client versions stop being selected
but remain private for explicit remote revocation. Payloads never become an
Agent or public Owner result.

This is a private enrollment component, not complete user OAuth integration.
Refresh, remote/local revocation, cleanup/quarantine of credentials from rejected
or interrupted exchanges, authenticated Owner handoff/GUI and native file
outputs remain open. In particular, refusal here does not claim revocation of
an authorization-server grant. The dedicated TLS fixture verifies the actual
SDK/PKCE/RSA and SQLite boundary, with schema-only service-account data for user
OAuth scope and explicit local Google token/certificate substitutes; it proves
neither live Google account permissions nor external delivery. Public count:
15/22.

Source-bound enrollment evidence:
[private PKCE/SDK enrollment validation](evidence/2026-10-30/google-chat-private-oauth-enrollment-validation.json).
Pending-secret compaction does not assert erasure of WAL, backups or other copies.

## Prepared user token lifecycle and rejected-grant disposal

The private token vault selects only the exact current stable user under the
explicit read/file-output grant. Valid cached credentials need no token request.
Actual Google Credentials SDK refresh has a FULL pre-wire intent, strict
post-refresh scopes/identity checks and atomic acceptance. HTTP429 delays stay
in an independent stable account/user/client budget through reopen and new
token generations. A new Owner code exchange also respects that deadline.
Authentication refusal and unclear refresh results block further automatic
refresh; a repeated call cannot blindly retry a possibly rotated refresh token.
Failed audit acceptance retains the old credentials and recovery state.

Local withdrawal commits before any Google revocation POST. Explicit remote
revocation uses the refresh token in a bounded fixed-endpoint POST body, never a
URL query, and needs no preceding refresh. Only a verified HTTP200 protocol
response with a durable receipt marks remote success. Refusal, redirect,
unexpected response, disconnect and failed receipt commits do not fabricate a
remote success. Repeating the same inspected decision does not issue another
POST. Old-scope credentials remain usable for disposal, not new file API use.

New enrollment requests `chat.messages.readonly` in addition to the native
`chat.messages.create` and OpenID scopes. The actual pinned discovery contract
requires a user read scope for `messages.get`; create alone cannot generally
reconcile an unclear user-authored file message. App authentication with
`chat.bot` only reads messages visible to the app and is not a general substitute.
Existing grants are never silently upgraded. The prepared Owner OAuth component explains the extra read consent; the
public account/file UI must retain that explanation and restrict native lookups to retained own
outbox operations. No general message-reading Agent capability is added.

Rejected exchanges and rejected refreshes retain newly returned capabilities
in a separate bounded private quarantine, never the active-token selector.
Metadata exposes the expected source user, not an invented verified returned
identity. Explicit snapshot-bound disposal invokes only the Google revocation
endpoint and compacts capsule payload after its durable confirmation while
keeping tombstones/audit. Failed refresh quarantine cannot rewrite its accepted
original enrollment. Missing/ambiguous token responses and process loss still
leave uncertainty; remote revocation is not asserted without a receipt.

Real-UID SDK/TLS fixtures cover refresh with/without new ID token, partial scopes,
wrong identity/nonce,400/429, post-body disconnect, audit failure, reopen/new token
generation rate preservation, local-before-wire denial, bounded one-shot remote
revocation and rejected exchange/refresh disposal. They use local Google-service
substitutes and do not prove a live Google account, external file delivery or
installed service acceptance. Authenticated Owner OAuth handoff and a separate Tk component are now prepared
as described below. Native outgoing files and public account-page integration
remain open; public count remains15/22.

Source-bound lifecycle evidence:
[private refresh/revocation/quarantine validation](evidence/2026-10-30/google-chat-private-oauth-lifecycle-validation.json).
Earlier enrollment-only CI is separately pinned to its exact source:
[enrollment checkpoint CI](evidence/2026-10-30/google-chat-private-oauth-enrollment-ci-status.json).

Prepared Owner OAuth administration now uses the fixed installed helper and an
actual live Root parent before dropping to the gateway UID. Its closed actions
prepare a PKCE consent URL, consume a full state-bound callback, inspect only
session/token/quarantine metadata, or explicitly withdraw an inspected token
generation or rejected capsule. The SDK, client secret, verifier and issued
credentials remain in the private worker; the Root caller receives bounded
metadata and receipts. A missing private service state root is created securely
before first setup. Existing insecure or symlinked custody is refused and left
intact, without automatic ownership or permission repair.

The prepared Tk OAuth component provides hidden client/callback inputs, explicit
consent, read-scope explanation, the checked Google consent URL, status selection
and separate withdrawal/disposal controls. It clears callback bytes before the
asynchronous handoff and invalidates old sessions/selections after client,
binding or connector changes. It distinguishes a local block from a confirmed
remote revocation. These controls are still a separately tested component; the
public Google account page, file publisher and installed service activation are
not complete. Google Chat remains outside the public fifteen-gateway count.

The corresponding process fixture runs the unmodified installed Root backend
and private worker with the actual Google SDK. Only disposable namespace DNS,
CA and Google HTTPS responses are local substitutes; systemctl's stopped state
is explicit fixture data. Actual Tk tests substitute only the privileged backend
responses, so they do not establish an installed Owner login or a live account.

Exact-source checks: [Owner OAuth handoff and Tk validation](evidence/2026-10-30/google-chat-private-owner-oauth-validation.json).
The previous lifecycle checkpoint's CI status is separately pinned:
[145e35e CI](evidence/2026-10-30/google-chat-private-oauth-lifecycle-ci-status.json).

Prepared native user-authored file output now connects the retained original /
native admission / parent relay evidence to immutable controller output
projections. The controller exports only explicitly marked artifacts from the
completed source session under the current delivery lease and separate
`allow_outbound_media` grant. Native Google output keeps a bounded first-byte
identity and private copies; missing, purged or changed custody is not silently
restored. The actual Hermes `_send_file` and `MediaFileUpload` receive a sealed
memfd, a generic filename and the exact source thread, never an arbitrary agent
or Owner host path.

User selection comes from the verified numeric source user and private token
vault. Mutable sender email and legacy credential slots cannot select a file
principal. The real Google discovery upload/create client uses bounded one-shot
HTTP and explicit journalled refresh only. Upload intent commits before wire
I/O; accepted upload references stay private and are reused without reupload.
Create intent commits before publication with stable client/request IDs and
`REPLY_MESSAGE_OR_FAIL`, overriding the native builder's thread fallback. A begun
or unclear create can only query its own retained client ID; a404 alone never
allows another POST. Known confirmed receipts need no new token/API access,
including after local logout. A revoked user cannot start a new file operation.
Explicit API401/403 and429 persist private-user auth/rate barriers, with stable
budget deadlines and no hidden SDK refresh or retransmission.

Google user-authored file messages are HUMAN messages. The pre-ACK receiver
therefore recognizes retained own client IDs/receipts, and narrowly refuses an
ambiguous matching pending file/caption/user/thread projection when Google omits
that client ID. It does not suppress unrelated human commands or authorize an
unknown sender. Own-write recognition uses the stable app account scope across
service-key rotation; replay/publication still requires its original credential
and source proofs. The refusal audit contains hashes/reasons, not copied file
capabilities or message bodies.

Space admission now accepts a legitimate partial nested Space description only
when its resource and all supplied type aliases agree with the outer Space.
Contradictory names/kinds still refuse before native processing. Canonical type
normalization is confined to the native builder input; existing raw originals,
semantic hashes and custody proofs are not rewritten.

These file paths are still prepared/private. Offline Owner decisions for file
upload/publication recovery and native output disposal, the complete public
account/file GUI, remaining Google ASR/video and production Pub/Sub daemon acceptance,
production controller Unix IPC and installed packaging remain open. No Google
file delivery, real consent entitlement or recipient read is established by the
local fixtures. No automatic retry or remote orphan deletion is claimed for an
unclear upload. The public software count remains15/22.

Exact-source checks: [native files and source-bound publisher components](evidence/2026-10-30/google-chat-private-native-files-validation.json).
Previous-source Owner OAuth CI is separately pinned:
[b3c975b CI](evidence/2026-10-30/google-chat-private-owner-oauth-ci-status.json).

Prepared Owner file recovery now inspects only bounded file/source/output
metadata. It separately proves the current original grant, unchanged app
credentials, committed native/parent source projection, original raw custody
and retained Root output bytes before allowing any retry. Upload recovery is
limited to two explicit attempts while no message create has begun. Publication
recovery is limited to four explicit independent non-delivery decisions. Each
snapshot-bound decision is audited and idempotent; replaying an old decision
never rearms a consumed attempt.

A publication permission is durably moved to `reconciling` before its own-ID GET,
not after it. The same live attempt receives a private opaque lookup object. A
GET404 can consume that object once and commit `consumed` before the unchanged
native create. GET200 instead confirms late acceptance without another POST.
An interrupted lookup, malformed JSON or receipt mismatch leaves no standing
permission for automatic create after reopen. IDs, uploaded reference, file
bytes, principal, source and thread remain fixed. Failed audit/receipt commits
roll back phase changes and preserve uncertainty. Legacy file journals add the
new upload retry generation without discarding existing unknown/confirmed rows.

The fixed Root/private worker now provides offline file/output inspection,
bounded retry decisions and exact-snapshot local output disposal. The prepared
Tk file component requires current selection, a nonsecret note, explicit
consent and separate independent non-delivery confirmation for publication. It
invalidates old selections and rejects private or mismatched response fields
before rendering. These decisions do not send anything or replace the separate
controller outbox recovery. Local disposal requires withdrawal of the original
output grant, keeps tombstones/audit and makes no remote Google deletion or
other-copy/backup/WAL erasure claim. Historical output/account association after
credential removal remains part of public management integration.

Exact-source checks: [offline file decisions, private SDK restarts and Tk component](evidence/2026-10-30/google-chat-private-file-recovery-validation.json).
Previous-source native-file CI is separately pinned:
[5d67f38 CI](evidence/2026-10-30/google-chat-private-native-files-ci-status.json).


## Full private Pub/Sub profile process acceptance

The private profile probe now builds the actual pinned Google adapter under the
separate gateway UID and runs `connect`, real SDK subscription inspection,
receive, durable native/relay admission, controller-component handling and native
SDK reply, disconnect/reconnect and replay as one loop. Local TLS/gRPC provides
only the external Google service fixture; the actual service-account SDK signs
RSA assertions and sends scoped OAuth metadata. The fixture checks durable
original or unknown-sender refusal custody independently before every ACK.
Unknown senders gain no mission rights and a replay after reconnect creates no
second source or reply.

Additional full-profile scenes exercise real gRPC `UNAUTHENTICATED`,
`RESOURCE_EXHAUSTED` with protobuf `RetryInfo(180s)`, and `UNAVAILABLE`.
Authentication refusal stops the receive channel; a rate refusal persists the
account budget without hidden SDK retries; transient transport loss recovers
after the profile backoff and admits only a new source. Root grant withdrawal
is also checked while a real server-side pull RPC is blocked: closing the SDK
channel must cancel that RPC, and a subsequently queued source receives neither
custody nor ACK. A cancelled server handler is allowed to drain before testing
the absence of new requests; cancellation cannot undo server work already begun.

These scenes are part of the prepared Google Chat CI workflow. They do not
establish production controller Unix IPC, installed service acceptance, speech
or video execution, a usable public account/pairing page or live Google delivery.
The public count remains **15/22**.


The private profile probe additionally runs the actual Controller in a separate
process under its controller UID65532, with a Root-bound inherited Unix socket;
the actual native Google gateway runs under UID65534 and uses the production
`gateway_runtime.call` for media begin/chunk, source receipt, outbox next and ACK.
A deliberately permissive fixture socket ensures the negative agent test reaches
kernel `SO_PEERCRED`; the agent is denied before any frame, and the gateway is
denied Owner mission-list methods. The gateway cannot read the controller's
private0700 directory/0600 database. Controller startup uses the installed
service's restrictive077 umask rather than the parent fixture's ambient umask.

Pub/Sub and HTTPS profile loops retain two unique Root-controller missions and
native replies across replay. The image scene carries exact SDK-downloaded PNG
bytes through the native codec and real Unix IPC into the separate controller's
FULL media chunks. Prepared Google policy is supplied through the Controller's
existing policy callback in this fixture; public registry/daemon activation and
installed systemd acceptance remain open. This is no live Google or model test.

Exact-source receipts: [full Pub/Sub profile](evidence/2026-10-30/google-chat-private-full-pubsub-profile-validation.json)
and [separate controller Unix IPC](evidence/2026-10-30/google-chat-private-controller-ipc-validation.json).


## Google voice and video through separate local processes

The media process scenes now retrieve a real bounded FLAC or synthetic MP4 via
actual Google discovery `MediaIoBaseDownload`, using correct512KiB range replies.
The native Google codec retains the source-bound attachment; the gateway sends
exact bytes through the kernel-authenticated Unix controller interface. The
separate controller calls its actual `execute` method. For voice this invokes
`speech_client.transcribe` and the actual socket-activated speech service under
UID65530 with the exact pinned local Whisper model. Only the verified transcript
enters the prompt, with no raw voice file attachment. FULL transcript custody
binds the result to the original audio checksum and model revision.

The video scene calls the actual separate decoder service for a bounded PyAV
thumbnail, validates the original source checksum/dimensions/duration, then
exercises actual Controller/HermesConnection attachment transfer of the original
MP4. The WebSocket peer in these tests is an explicit local protocol-service
fixture: it validates attachment bytes and prompt contents, returns a streaming
acknowledgment and a labelled fixture terminal event. This verifies local byte,
process and protocol handling, not actual Hermes inference or model video
understanding. Replayed and unknown sources start no second download or prompt.


A separate voice-withdrawal scene waits for the real native STT child to start,
then atomically withdraws the Root grant. The actual speech client cancels its
socket request and the service joins the native child. No transcript is stored,
no prompt is submitted, no completion is fabricated, and original custody stays
intact. The speech service remains available. This scene passed twice. The
fixture relay now handles a concurrently revoked publication just as the
production loop does; errors under unchanged authority still fail the test.
An earlier fixture loop exited on that intentional refusal after the worker had
already stopped and left a stale status marker; no production gate was relaxed.

Exact-source receipt: [native voice/video, withdrawal and media regressions](evidence/2026-10-30/google-chat-private-local-media-validation.json).


## Durable public identity for historical private profiles

Profile creation and matched Root Owner recovery now retain an immutable public
`account-identity.json` under the private app profile lease. It stores only the
project, service-account email and expected numeric bot resource. These fields
recompute the original private profile name and survive service-key/subscription
changes. No private key, access/refresh token, OAuth client secret, transport TLS
material, source content or new route grant is stored in this descriptor. It is
a declared app identity, not evidence of Google authentication or entitlement.

Legacy profiles acquire missing metadata only from the current matched Root
account for that exact profile; their existing SQLite journals are not rewritten.
Same-identity reopen/rotation preserves the descriptor bytes/inode/timestamp.
Creation uses a synced private temporary file and atomic non-replacing link;
a failed exclusive temporary-name creation preserves an existing colliding file;
existing mismatched/damaged/symlinked/hardlinked or permissive records refuse and
are preserved for inspection. No automatic metadata repair or custody deletion
is performed. Root/agent/supplementary-Root identities cannot read/write this
private helper. Owner selection of a different historical profile never writes
the current account's descriptor into it.

This provides a nonsecret identity anchor for management after credential
removal. The separate retired-account Owner actions/UI and historical output
association remain in progress; the descriptor itself authorizes no API access,
refresh, send, inference or automatic provider/gateway permission.

Exact-source checks: [private identity migration, custody and SDK/Owner regressions](evidence/2026-10-30/google-chat-private-account-identity-validation.json).


## Historical token status and withdrawal after account removal

A separate fixed Root/private-UID historical worker now supports profile
inventory, token metadata and explicit token withdrawal without a service-account
key. The authenticated Root backend first quiesces/verifies the gateway service,
then pins the trusted public configuration (including actual file absence),
passes only closed metadata/selectors through stdin and drops all extra groups.
The worker verifies the actual live Root parent, installs parent-death and
NoNewPrivs guards, applies resource bounds, acquires the real private profile
lease and revalidates its immutable public app descriptor before I/O.

Retained OAuth credential/client hashes are checked against that public app
identity in the private process. Active enrollment, route selection, refresh
and file API loading still require their original full-account/current-grant
checks; public metadata does not satisfy those checks. No active connector,
policy grant or synthetic service-account credential is recreated for cleanup.
Status displays the actual published file-grant count as information and marks
`active_authorization_returned=false`. Token/client-secret bytes remain private
and are added to shared bounded credential redaction before any metadata reply.

Historical withdrawal requires the exact app snapshot, token ID/generation,
explicit Owner confirmation and a nonsecret note hash. The FULL local token and
transport denial/audit precedes the single fixed Google revocation POST.
Unknown/declined/rate-limited outcomes retain local denial; a repeated decision
cannot repeat an unclear write. A confirmed existing receipt is reused without
another HTTP request. Original tokens/journals remain private custody; secure
WAL/backup erasure is not claimed.

The process fixture first performs real pinned-SDK Flow/RSA/PKCE user enrollment,
then removes the active connector and every service-account credential/config
file before invoking the actual Root historical backend. It independently sees
local denial and the durable write intent before accepting the TLS revocation
request. Metadata also works with optional SDK/Hermes paths removed. Real kernel
UID/parent, flock, identity-tamper, pending-publication and parent-death checks
remain enforced. Google endpoints/DNS/CA and declared systemctl service state
are explicit local fixtures, not live Google or installed systemd acceptance.

Historical quarantine disposal, output association/recovery, missing legacy
identity recovery and the public management GUI/CLI remain in progress. These
functions do not activate Google Chat publicly; the software count stays15/22.

Exact-source checks: [historical Owner token status/withdrawal and regression](evidence/2026-10-30/google-chat-private-historical-tokens-validation.json).


The historical worker also supports rejected-token inventory and explicit
snapshot-bound disposal after active configuration and service-account keys are
removed. Capsule scope/project, canonical payload checksum and nonactive state
remain checked against the retained public app identity. Metadata works without
optional SDK/Hermes runtime paths and captures private capsule tokens in bounded
redaction. No verified-user or API-use authority follows from a rejected capsule.

The actual Root handoff requires selected app/capsule snapshots, explicit
confirmation and an audit note. FULL `revocation-pending` state plus the exact
Owner decision `writing` intent precedes the one fixed revocation POST. Only a
confirmed response and durable receipt compact the private capsule; uncertain,
refused or rate-limited outcomes preserve its guarded payload. Repeating a
completed decision reuses its original receipt without a second request. This
does not claim erasure from WAL, other copies/backups or external account state
beyond the checked revocation response.

The historical process fixture now retains the wrong-user capsule until after
connector/key/config removal. Its independent TLS server checks the committed
pending/decision state before receiving the revocation. Root/private UID,
metadata tamper, actual profile lock, parent lifetime and pending-publication
gates still apply. The active Owner disposal path and full OAuth lifecycle also
remain tested. Historical output association/purge, legacy missing-identity
recovery and public GUI/CLI/daemon setup remain open; count stays15/22.

Exact-source checks: [historical rejected credentials and regression](evidence/2026-10-30/google-chat-private-historical-quarantine-validation.json).


## Historical output ownership

Each retained output now has an immutable per-file connector/app association,
independent of service-key epochs. It binds the exact delivery/offer, original
credential hash, binding digest and public filename/MIME/checksum projection.
Ownership fields and that immutable projection share a checksum. An authorized
current Root output route records it before fetching bytes; a validated retained
native FileLedger proof can recover the index for a legacy output. Metadata does
not authorize reuse of an old file for a different account, source or grant.

Current and historical Owner inventories can therefore find old output copies
after key rotation or configuration removal. The separate Root historical worker
also exposes explicit snapshot/ownership-bound local output disposal without a
service-account key or optional SDK. Actual published original grants still
block deletion. Failed audits roll back byte disposal; repeated decisions reuse
the receipt. Ownership, checksum identity and audit tombstones remain after
local bytes are purged, with no remote deletion or other-copy/WAL erasure claim.

Legacy reindexing preserves bytes and accepts only an exact current Root
binding/current credential or a validated native file proof. Unproven legacy
rows remain unassociated and untouched rather than being assigned by filename,
checksum coincidence, reused connector name or a new account. Explicit recovery
for those orphaned rows and missing legacy account identity, plus public GUI/CLI
and production activation, remain in progress. The public count stays15/22.

Exact-source checks: [output ownership, historical Root disposal and regression](evidence/2026-10-30/google-chat-private-output-ownership-validation.json).

## Unassociated local output recovery

Root can inspect and explicitly dispose of retained output bytes whose legacy
records cannot prove an app association. This global recovery path acquires all
Google profile leases and checks the actual current original output grants;
it does not infer an account from a filename or require a service-account key.
The decision binds the inspected snapshot, explicit confirmation and Owner note.
An intervening proven association requires a fresh account-specific inspection.
Audit and identity tombstones remain, and replay reuses the local receipt.
No external deletion, backup or WAL erasure is claimed.

Purged tombstones no longer consume the live output quota (128 files/48 MiB).
A separate 65,536-record history bound preserves the audit limit. Inventories
show retained bytes before purged history so older live files remain reachable.
Public Google Chat setup and activation remain in progress; count stays 15/22.

## Owner controls for retained accounts

The authenticated graphical administration now offers **Gateways → Google Chat:
entfernte Konten und lokale Altbestände verwalten** independently of an active
connector. It lists known public app descriptors separately from opaque profiles
whose original identity is missing. Selecting a profile clears all old results
and confirmations; the Owner must load and select a fresh token, rejected capsule
or local output snapshot, enter a non-secret reason and explicitly confirm.
Background results from an earlier selection are discarded. Unexpected private
fields are rejected before rendering. Global unassociated output recovery does
not infer or require a selected account.

The same Root backend is available through `haos-owner gateway
google-chat-retired`. Read-only actions are `profiles`, `tokens`, `quarantines`,
`outputs` and `unassociated-outputs`; account-specific actions require
`--profile`. Withdrawal actions are `revoke-token`, `dispose-capsule`,
`purge-output` and `purge-unassociated-output`. Each requires the exact inspected
`--id`, `--snapshot-sha256`, `--note` and `--confirm-inspected`; account actions
also require `--profile`. The CLI reloads metadata and refuses stale snapshots.
Secrets are never CLI arguments, JSON output or GUI details.

Inspection stops the gateway and does not automatically restart it. Revocation
can contact the fixed Google revocation endpoint after durable local denial;
it does not send a chat message. An uncertain remote result remains uncertain.
Local output disposal refuses any active original grant and preserves audit
tombstones. Missing legacy app identity still prevents account-specific token
withdrawal until explicit original-identity restoration succeeds; it never
triggers guessed identity or credential reconstruction. Public-path acceptance
and status management review continue. The accepted software count stays 15/22.

## Missing legacy public identity

If an older profile has no `account-identity.json`, the Owner can supply the
**original** public project ID, service-account email and numeric bot resource in
the historical recovery page. The same operation is available as
`gateway google-chat-retired restore-identity --profile ... --project-id ...
--service-account-email ... --bot-user ... --note ... --confirm-inspected`.
No private service-account JSON or token is requested.

The public fields must produce the exact original stable account scope and
double-hashed retained profile name. A different app, alias or bot is refused
before writing. Root records a durable intent, quiesces the gateway and uses
the existing authenticated private worker and actual profile lease. The
non-replacing, fsynced descriptor writer preserves existing malformed metadata,
symlinks, hardlinks, permissions and custody rather than attempting repairs.
An existing matching descriptor is idempotent. No profile is created by this
procedure, and no keys, tokens, API capabilities or active sender grants change.
After restoration, fresh historical token/quarantine/output inspection and
separate explicit withdrawal decisions remain mandatory. If the original public
values are unknown, preserve the opaque profile and obtain them from the Owner's
original project records; HAOS does not guess or infer an account.

The actual Root/private-UID process fixture removes only its disposable legacy
marker after real SDK enrollment and removes all active connector/key/config
data. Metadata restoration and subsequent historical inspection work with SDK
and Hermes imports hidden. Missing consent, a foreign bot, a held kernel lease
and an already damaged descriptor are refused. No network request accompanies
identity restoration. Tk and CLI use the same Root backend and invalidate prior
consent when the public identity or selected profile changes.
