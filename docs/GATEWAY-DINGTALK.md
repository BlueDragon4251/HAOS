# DingTalk — owner setup and integration

DingTalk now has a public HAOS software setup path, bringing the gateway registry
to thirteen of the pinned 22 platforms. This is not live-account or installed
acceptance. Credentials remain in the separate gateway identity; the agent gets
only scoped local mission/artifact capabilities.

The exact pinned upstream `dingtalk` extra contains `dingtalk-stream` 0.24.3 and
`alibabacloud-dingtalk` 2.2.42. Its frozen extras now join the existing nine extras
with one targeted hash-pinned Tea-OpenAPI 0.4.6 compatibility correction.
The frozen 0.4.5 declares Cryptography <49; 0.4.6 permits <51 on Python 3.9+.
HAOS retains Cryptography 50 and MSAL 1.39.0 unchanged. The reviewed upstream
code changes concern throttle-header classification; RSA/HMAC signing and
positive/invalid retry headers have explicit native compatibility contracts.
Preparation rejects an unreviewed extra set. Build/CI run the native codec probe.

Prepared identity requires exact app ID/secret, corporation and robot code. No
caller API URL, plugin setting, alternate auth field or unused token is accepted.
Private policy requires exact native sender and conversation IDs, account scope,
fresh timed grants and separate media/output permissions. Staff/display aliases
and `isAdmin` never grant HAOS rights. The pinned native callback has no topic
route: nonempty topic/thread input is refused instead of widening a chat grant.
Group processing requires the native boolean bot-mention indication by default.

Independent projection validates strict bounded JSON, exact app/robot and both
corporation fields, sender/chat, original timestamp and current grant before
invoking actual SDK models and pinned native pure text/media codecs. Existing
DingTalk recognition text remains voice and requires voice consent; this is not
an assertion of HAOS local ASR. Rich media resolver aliases are canonicalized on
a copy for the actual codec; conflicting codes are refused, original bytes are
unchanged. Video needs video permission even when the pinned codec labels it as
a file. App secrets and private session-reply URLs/capabilities cannot become
agent goals. Incoming resource retrieval and sealed relay dispatch are described
below; shared controller mission acceptance remains pending.

Private SDK token and connection-discovery operations now have closed scopes.
The actual SDK request builders remain in use. Only fixed API paths and exact
credential/subscription/header shapes are admitted; wildcard events, arbitrary
transport options, redirects, compression and unbounded or malformed responses
are refused. TLS verification stays enabled. Cookie state is cleared rather than
forwarded between SDK requests. Only observed token-cache contents may be reused;
metadata changes or another boundary's cache are refused. Native expiry-buffer
refresh is tested without mocking time. Discovery may produce only a reviewed
DingTalk WSS endpoint and private ticket; the long-running socket is not connected
by this helper. SDK logging is suppressed at its private client, with escaped
credential spellings also registered for redaction. No raw token/ticket is an
owner account-status result. The SDK's unrelated public UDP address probe is
removed from the informational `localIp` hint.

A one-shot account action runs the actual pinned Hermes `_get_access_token`
wrapper and DingTalk SDK under the separate private gateway identity. Parent and
worker check real UID/GID/no supplementary groups and fresh root publication.
The fixed root-owned interpreter, bounded pipes, real CPU/memory/file limits,
30-second worker alarm, parent-death SIGKILL and parent cancellation/revocation
checks constrain that action. Success proves app authentication only: corporation
and robot identity remain unverified, and no message is sent. This helper does
not authorize a sender, install plugins or connect a gateway by itself.

Private Stream transport now uses the actual SDK subscription/discovery,
callback parsing and ACK codecs. Its separate gateway-UID worker admits frames
inline through independent approval, waits for a parent receipt and only then
allows the SDK ACK. The parent retains exact original bytes and the native input
in separate FULL-synchronous private SQLite journals. Duplicate callbacks cannot
change their original body, grant, account epoch or retained reply route; a
refreshed session bearer on replay never replaces the first original.

The worker owns one verified WSS connection, bounded frames, queue/backpressure,
heartbeat deadlines and parent IPC. It refuses HTTP redirects and wildcard EVENT
subscriptions. HAOS deliberately supplies the socket lifecycle around the actual
SDK codecs because native SDK.start swallows cancellation, reconnects internally
and creates unbounded background tasks. Parent/publication withdrawal and kernel
parent-death SIGKILL terminate the private worker. All app/token/ticket/reply URL
material stays private. The new raw journal has 64 MiB/128 live-original bounds;
it refuses capacity overflow instead of dropping acknowledged input.

Nine actual UID/TLS/process socket contracts pass against offline loopback API
and WSS domains, including replay on a fresh worker, pre-ACK custody, agent UID
denial of original/WAL/credentials/stdin, withdrawal, parent death and WSS
401/429/302 without hidden SDK retries. The reconnect supervisor in this probe
is explicitly a fixture at that checkpoint. A subsequent private profile now
connects the actual native Hermes `_on_message` handler through the durable MRO
and independent relay admission, with fresh supervised worker reconnect and
persistent account-scoped authentication/TLS blocks and retry deadlines.
A separate nine-case actual UID/TLS profile probe tests this production supervisor,
including one original/input/relay obligation across reconnect, withdrawal and
401/429/302 decisions surviving connect, close and profile recreation.
The native handler is exercised only for a retained input claim; staff aliases,
raw SDK messages, session-webhook caches and direct callback/token/reaction methods
cannot bypass that context. Text, vendor-recognized voice text and independently retained binary resources
are connected to native dispatch. No native download code or CDN URL becomes an
agent attachment: only sealed local media IDs are admitted. Native custody also tests a crash window between original and
input commits, finite durable receipts and cancellation/backpressure. No mission
or external delivery is claimed by these custody/socket checks.

A private per-write reply path now invokes the actual pinned native sender and
markdown formatter in its own bounded gateway-UID subprocess. It may write only
the exact retained session URL, source, body and current read/reply grant. The
strict httpx boundary keeps TLS validation enabled, refuses redirects and cookies,
limits responses and requires a valid native `errcode: 0` vendor acknowledgement.
HTTP 200 with a nonzero native code is a rejection. The native sender's random
UUID is never treated as a remote message ID: its private result carries a local
`haos-dingtalk-…` acceptance proof, `remote_message_id: null` and
`recipient_read_verified: false`.

The parent writes a FULL-synchronous immutable intent before starting the worker.
Confirmed replay uses its existing local vendor-acceptance proof without another
write. A begun write with a dropped, truncated, malformed or otherwise ambiguous
response is quarantined as uncertain, including after process/profile restart;
a new attempt does not implicitly resend it. HTTP 401/429 refusals retain account
blocks/deadlines. Expired session routes are refused before writing. An inbound
WSS interruption does not withdraw a separately valid HTTPS reply route: that
requires a live profile, fresh owner authority, an unchanged account and no
explicit stop or auth/TLS block. A transient socket interruption cannot itself
create or expand reply authority.

Incoming resource reads now invoke the actual Hermes `_get_access_token` and
`_fetch_download_url` helpers, real generated Robot SDK/SPI and native response
models in a separate bounded gateway-UID worker. The generated SDK retains
port=80/default-zero runtime hints even for HTTPS; HAOS admits those exact pinned
shapes while fixing the actual transport to verified HTTPS API port 443 with
independent deadlines. Only the approved original download code and robot may be
looked up with an observed private token. High-privilege app/token material cannot
become a returned content URL.

The separate credential-free content client pins reviewed numeric DNS answers,
accepts ordinary global unicast only, validates TLS, preserves signed escaped
paths/queries and bounds redirects and bytes. Loopback, LAN, link-local, CGNAT,
multicast and IPv6 translation/tunnel destinations are refused. API credentials
and cookies never follow a content URL. Content-server 403/429 decisions stay
separate from account-auth failures; a native input retains a content rate deadline
rather than prematurely exhausting its retry budget or blocking the whole account.

The actual native message handler receives retained media through the durable
MRO and context-bound local IDs. PNG/JPEG images, document bytes, voice bytes and
ISO video containers retain their separately approved kinds; decoded audio/video
cannot bypass consent through a document label. Resource and input replay retain
byte hashes and reuse their committed cache/source pointers after handler failure.
The first verified byte hash and MIME are now committed as a resource intent
before blob insertion. If capacity/crash leaves that blob missing, recovery can
fetch only the same hash/MIME; an existing purged/damaged cache row is never
automatically restored. Changed bytes fail the input for explicit owner review,
instead of triggering automatic repeated reads. SQLite-full rollback preserves
the original capacity error even when SQLite already aborted its transaction.
Administrative resource decisions still require their owner management path. Fourteen actual UID/network cases cover
reads and sealed relay, and the fifteenth connects actual verified WSS capture,
pre-ACK custody, Robot lookup, binary retrieval and relay crash/retry. The production
public DNS resolver is exercised without mocks: global-looking fixture addresses
are assigned only to loopback inside a fresh network-none namespace. There is no
external interface or Internet delivery. Wave/PDF/video fixtures verify private
byte transport and consent, not speech recognition, playback or document decoding.

The earlier private stages below are now connected to authenticated owner setup,
per-part/source/cache management and the shared public runtime. Each fixture
boundary still applies; none proves external DingTalk delivery.

Local codec, SDK/TLS and private process fixtures have distinct boundaries.
Loopback API substitutions, temporary fixture CA trust, supplied owner policy
and synthetic identities are not live authentication, external delivery,
installed-system or hardware acceptance. No real external messages are sent by
these probes.

The outgoing worker now also has actual UID/TLS negative lifetime evidence. The
extended fifteen-case process probe cancels and revokes a begun HTTPS write,
kills its parent while both WSS and reply workers exist, and dribbles an HTTP
response across the real 30-second worker alarm. All credential-bearing workers
terminate. A parent crash leaves a durable writing row that becomes uncertain
on actual profile recreation; neither recreation nor another attempt resends it.
The probe synchronizes its receive-ACK assertion before deliberately killing a
parent, so an unrelated intentionally interrupted callback cannot invalidate
that fixture. No ACK, journal, worker-lifetime or no-resend assertion is removed.

The extended seventeen-case real UID/network probe also imposes an actual SQLite
page budget between the source intent and blob insertion. It verifies identical
byte recovery after restoring capacity and quarantine of changed bytes. No write
or UID/socket behavior is mocked. These cases retain the complete WSS-to-media
relay checks; no assertion is weakened to make storage recovery pass.

The private reply credential now optionally selects `reply_mode: robot`; omitting
it preserves `session` behavior. There is no automatic fallback or mode switch.
The Robot mode uses the actual pinned Hermes token/SDK helper, generated
`OrgGroupSend` or `BatchSendOTO` builder, native SPI and response model. Group
writes target the exact approved conversation. Bot direct messages use one staff
routing ID from the exact retained authenticated original, after canonical opaque
sender/chat/account authorization; that hint never authorizes a sender. A
missing direct-recipient hint is refused. Owner setup must explain the required
Robot API permissions; they remain account-dependent live checks.

Stable replies use fixed verified HTTPS Robot endpoints, one request per immutable
intent, bounded strict JSON and no redirects/cookies. A native `processQueryKey`
is only provider queue acceptance, never a remote message ID or read receipt.
Recipient-invalid decisions reject the write; explicit flow control retains a
retry deadline. Unknown recipient decisions, missing keys, malformed responses,
connection loss and withdrawal after a possible write remain uncertain. The
existing durable per-write journal prevents implicit resend. Expired or absent
session URLs do not prevent an explicitly approved Robot-mode write, and do not
cause any session fallback. This SDK contract alone does not establish GUI or live-account acceptance.

Private offline management now exposes finite transport/account/write inventory,
account-authentication recheck and inspected non-delivery retry decisions through
the unprivileged recovery worker. Clearing an authentication block preserves rate
waits, TLS blocks and uncertain writes. Releasing a private write requires its
exact inspected snapshot, explicit non-delivery confirmation, current read grant
and an immutable owner/note/policy audit entry. It sends nothing and still
requires independent controller reconciliation.

Original-source inventory returns hashes and byte counts, never private payloads.
Explicit disposal requires withdrawal/change of the original grant, a fresh
snapshot and audited owner confirmation. It retains source proofs/tombstones;
failed audit insertion rolls back byte removal. Repeated identical decisions are
idempotent. Existing private path/UID/regular-file/single-link checks refuse
symlinked or hardlinked stores. Disposal does not claim erasure of WAL remnants,
other ledgers, controller/agent copies or backups. The owner controls described below now invoke these functions through the
authenticated stopped-service handoff; private functions alone are not that proof.

Nine additional actual UID/chroot/SQLite recovery cases exercise real gateway
account dispatch with and without a ledger, root/agent denial, retained waits,
uncertain-write release and grant-withdrawn source disposal. They run without
Hermes source or optional SDK imports. Their policies and retained source bodies
are fixtures, not live callback authentication or installed-owner acceptance.

Private sealed-output uploads now have their own fixed interpreter/process path.
The worker revalidates the exact retained canonical source, read grant, separate
output approval, explicitly selected Robot mode, immutable output checksum and
format before using the app token. Voice/video require their separate approvals.
The actual pinned Hermes token helper and Stream SDK multipart builder are used.
Only `oapi.dingtalk.com/media/upload` may receive the single exact multipart body;
API credentials remain private and cookies/redirects are refused. Uploads carry
bytes, never agent host paths. Strict bounded native `errcode`, resource type,
media key and timestamp checks distinguish explicit refusal from an uncertain
write. A returned private media key is not an outbound-message receipt.

The reviewed upload formats follow the official
[media upload API](https://open.dingtalk.com/document/orgapp/upload-media-files)
and [Robot message types](https://open.dingtalk.com/document/orgapp/types-of-messages-sent-by-robots).
HAOS additionally limits bytes, uses fixed path-free result names, checks declared
format signatures and refuses known image/audio/video bytes disguised as a PDF.
The private Robot voice path selects AMR-NB, which both interfaces document.

AMR conversion uses `libopencore_amrnb` already present in the existing frozen
PyAV runtime: no new package, lazy install, external program or cloud codec is
introduced. The existing credential-free local speech identity now accepts one
additional closed `amr` operation. It resamples bounded decoded mono audio to
8 kHz, encodes fixed 12.2-kbit/s AMR-NB with DTX disabled, re-decodes and verifies
complete frame duration. Source duration and encoded duration remain distinct in
the source-bound receipt. Actual local Hermes ASR recognizes the converted
reference. Gateway/controller Unix peers, socket trust, revocation, disconnect
cleanup and long binary replies are exercised by the extended real-UID speech
probe. These codec/RPC checks do not claim DingTalk delivery or device playback.

Those standalone upload/AMR contracts preceded their parent batch journal,
artifact handoff and Robot media-message connection. The following stage now
connects those pieces; owner/GUI activation is covered separately below.

The private shared runtime factory now constructs the actual DingTalk profile
with exact parent/connector/policy/inbox context. Delivery metadata, credential
redaction and sealed-output preparation are connected without public registry
activation. The independent controller export gate also admits explicitly
prepared DingTalk policies; unknown or ordinary unsupported policies remain
refused.

Prepared output reads only the authenticated Hermes artifact API for exact
marked files in a completed source session. The controller retains its first
snapshot even if the agent later changes a file. Gateway preparation verifies
bounded chunks and hashes, scans private material before conversion, preserves
PNG/JPEG bytes, retains native AMR voice bytes, and builds a deterministic ZIP
for formats outside the Robot document templates. No agent host path is opened
by the gateway. MP4 uses a source-bound PNG preview from the existing separate
credential-free local service, with duration/dimension/aspect checks and fixed
native codecs. Voice/video messages require their separate approvals. Codec
outputs retain their first committed bytes and are not regenerated after a
purged or damaged cache entry.

Before any caption/upload, the entire ordered batch and caption are committed as
one immutable FULL-journal manifest. Each upload and media message has its own
source/grant/account/part-bound intent and hashed private receipt. Confirmed
parts are reused across attempts; writing/uncertain parts cannot implicitly
repeat after cancellation, crash, disconnect or restart. Explicit native rate
waits persist, and an authentication block cannot erase a prior rate deadline.
SQLite-full while recording acceptance leaves the part uncertain. The original
batch cannot become ordinary text or lose/add files, change caption, or replace
bytes during recovery. Native media queue acceptance is recorded only as a local
proof, never a remote message ID or recipient-read claim.

Explicit disconnect/close now publishes its stop intent before waiting for the
profile's lifecycle lock, so a pending write cannot delay its own withdrawal.
Connection epochs and an irreversible closing latch prevent an older queued
connect from reviving a later stop. Actual UID/TLS process cases test both stop
operations for session, Robot direct and Robot group replies.

The controller-artifact probe uses a real authenticated pinned Hermes backend,
but completed sessions and connected transport are fixtures; its speech RPC
substitution runs the actual native codec. Separate actual-UID socket tests
exercise the real credential-free codec service. The continuous media process
probe uses the actual shared factory, WSS pre-ACK custody, native handler, private
byte upload and Robot media-message workers, FULL batch/part journals, replay,
revocation and process lifetime guards. Its already-prepared output bytes remain
fixtures, so it does not claim a real agent result or provider inference.

## Owner setup and identity pairing

1. In the DingTalk developer console create an internal enterprise app, enable its
   bot and Stream mode, and make it available to the intended enterprise users.
   Copy exact **Client ID/AppKey**, **Client Secret/AppSecret**, **Corporation ID**
   and **Robot Code**. No inbound port or callback listener is needed for Stream.
2. In HAOS management → Gateways select `dingtalk`, enter those four values and
   choose `session` or `robot` explicitly. Saving/rotating the account withdraws
   its existing grants and leaves the gateway service stopped. The masked secret
   is cleared on account/mode changes and after handoff.
3. Use **DingTalk-Konto ohne Nachricht prüfen**. It checks app authentication
   privately and sends no chat message. It cannot verify the corporation/robot
   assignment or message permissions. Correct credentials/permissions before
   **DingTalk-Anmeldung erneut erlauben**; retained rate waits and uncertain
   writes remain protected.
4. To discover the real opaque `senderId`/`conversationId`, choose
   **DingTalk-IDs ohne Freigabe erfassen**. HAOS shows a random 128-bit one-time
   challenge, valid for 60 seconds. Send that text yourself to the intended bot;
   mention the bot in a group. HAOS sends no outgoing challenge. A separate
   gateway-UID process checks fixed TLS/WSS discovery, the actual native frame and
   message codecs, corporation/robot, timestamp, sender and challenge. It commits
   metadata before native ACK. No original text, session URL, staff alias or
   credential is returned to the GUI. Already-approved ordinary traffic is
   retained for later dispatch while the service is stopped.
5. The captured IDs remain **untrusted and unauthorized**. Inspect sender/chat,
   choose a HAOS identity and explicit mission permissions, then approve pairing.
   No display name, staff ID, `isAdmin`, unknown sender or plugin grants rights.
   New grant timestamps prevent the old challenge from becoming a mission.
   The pinned adapter has no topic-thread route: thread must remain empty.
6. Approve images/documents, voice, video and output files separately. Voice needs
   the configured local speech service. Output files require read permission and
   explicitly chosen `robot` mode, with matching native Robot API permissions
   for sending bot group messages and bot single-recipient messages. Enable the
   app permissions required by the DingTalk console for those exact operations.
   Missing direct-recipient staff routing information is refused after canonical
   sender approval; it is never substituted for that approval. Session mode keeps
   its original bounded webhook expiry and never silently switches reply mode.
7. Start the gateway service and inspect status. Revoking a grant, stopping the
   service or removing the connector kills active workers and prevents further
   use. Local removal does not revoke the enterprise app at DingTalk: disable or
   rotate it in the DingTalk console when provider-side revocation is intended.

## Owner recovery and disposal

The gateway ingress panel displays text and individual upload/media-message
states. Unknown write outcomes remain blocked across restart and later attempt
numbers. Only an inspected exact part/snapshot plus independent confirmation of
non-acceptance can release its private retry lock. Controller reconciliation is
separate and never sends a message by itself. Accepted writes cannot be released.

A complete media batch exposes its local aggregate acceptance proof only when
its caption (if any), every upload/cover and every reply has a committed receipt.
This proof can help the owner reconcile a lost controller ACK. It is not a native
remote message ID, recipient delivery or read confirmation. Partial/uncertain
batches expose no aggregate acceptance proof and never auto-repeat.

**Gespeicherte DingTalk-Quellen verwalten** and **Gespeicherte
DingTalk-Konvertierungen verwalten** return metadata/hashes and sizes, not bytes.
Disposal requires withdrawing/changing the original grant, loading a fresh
snapshot and confirming one exact item with a non-secret note. Audited FULL
transactions retain proof/tombstone rows; failed audit insertion rolls back byte
removal, and repeated identical decisions are idempotent. Old bytes cannot be
silently regenerated. Other copies, backups and SQLite WAL erasure are not claimed.

CLI equivalents include `haos-owner gateway setup … dingtalk`,
`dingtalk-account`, `retry-dingtalk-auth`, `dingtalk-sources`,
`dingtalk-output-cache`, `purge-dingtalk-source`,
`purge-dingtalk-output-cache`, `approve-dingtalk-retry` and
`approve-dingtalk-part-retry`. Decisions require explicit IDs, attempt/snapshot,
inspection and non-acceptance confirmations as applicable. Credentials use secure
owner entry and never command-line arguments.

The activation receipt records exact source hashes, minimal/full runtime tests,
real root/gateway/agent UID checks, actual native SDK fixtures and Tk exercises at
both screen sizes. Service control/audit or account responses replaced by fixtures
are explicitly named in each receipt. No real external message, account permission,
provider inference, installed boot, device playback or final release is claimed.

Source-bound activation evidence: [2026-10-30 owner/public validation](evidence/2026-10-30/dingtalk-public-owner-validation.json).
