# Google Chat — private integration in progress

Google Chat remains outside the public HAOS registry and GUI. The public software
count remains 15/22 after Buzz. The prepared modules below do not constitute a
working installed gateway or live Google Workspace acceptance.

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

## Remaining before public activation

- Full production-daemon/root-socket acceptance of the prepared private profile,
  with the complete private Pub/Sub lifecycle now tested separately below.
- Durable native dispatch into the independent root mission/controller queue,
  cancellation, outbox authority and inspected owner recovery/status/logout.
- Safe input attachments, local voice and video, sealed controller-exported
  outputs, per-user OAuth setup/refresh/revocation and native upload. The pinned
  adapter requires user OAuth for uploads; service-account auth alone does not
  provide native file delivery. No chat-triggered setup may grant HAOS rights.
- Complete usable owner account/pairing/media/OAuth/recovery GUI, CLI, installed
  packaging, full kernel/UID/process lifecycle and production end-to-end tests.

The optional frozen `google-chat` extra is installed only in the dedicated local
validation environment and dedicated prepared-contract CI workflow. Installed
runtime extras have not been expanded yet. No runtime package versions or
hash-pinned HAOS overlay dependencies were updated.

Source-bound evidence:
[prepared contracts](evidence/2026-10-30/google-chat-private-primitives-validation.json)
and [actual UID receive/relay checks](evidence/2026-10-30/google-chat-private-receive-validation.json).
Loopback HTTP, certificate and SDK ACK-queue fixtures do not establish live
account privileges, subscription authorization, public callbacks, inference,
external recipient delivery/read status, installed OS or release acceptance.

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
