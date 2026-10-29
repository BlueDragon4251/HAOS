# Feishu / Lark — private integration in progress

Feishu remains outside the public HAOS gateway registry and GUI. Installing the
bundled adapter or SDK is not a working authorized HAOS gateway. Eleven other
public paths are listed in [Gateways](GATEWAYS.md).

The frozen runtime now includes the pinned upstream `feishu` extra: actual
Lark OpenAPI 1.6.8 and requests-toolbelt 1.0.0. The existing eight extras and
hash-pinned overlay, including MSAL 1.39.0, remain unchanged. Preparation checks
the exact upstream source hashes and refuses an unreviewed extra set. The
native SDK probe uses real Hermes builders, real Lark models and actual
loopback HTTP for tenant-token acquisition, bot lookup, authentication failure
and rate limits. It does not contact a real Feishu/Lark app or send a message.

Prepared private identity validation requires an exact app ID/secret, explicit
Feishu or Lark brand, tenant key and bot open ID. No arbitrary API URL, plugin
settings, display-name or alternative user-ID authorization is accepted. Sender
open IDs, chat IDs, optional native topic IDs and fresh timed owner grants are
separate. Account scope binds brand/app/tenant/bot. Media permissions default
to denied and require appropriate mission rights. Websocket mode accepts no
unused webhook secrets; webhook mode requires verification token, encryption
key and reviewed HTTPS listener material for `/feishu/webhook`.

Actual Lark event decoding retains millisecond timestamps as strings and
keeps `thread_id` distinct from the quoted `root_id`. Its SDK token cache uses
app-ID keys; the private read boundary now namespaces tokens by complete
credential identity and brand. Socket-mode SDK paths still need their own
reviewed transport boundary. Native send retries and reply fallbacks also need
independent durable HAOS limits. HAOS will not delegate owner identity to the
upstream allow-all or pairing defaults.

Prepared private HTTPS receive authentication, persistent ingress and native
replay are implemented and tested below. Public activation, socket-mode
transport, media/voice and complete owner GUI/recovery integration remain
open. Private single-reply delivery is implemented and tested below.
Local SDK and identity tests do not establish live-account, external delivery,
installed OS or hardware acceptance.


Independent input projection now checks bounded duplicate-free finite JSON,
application and both tenant fields, exact open sender/chat/native topic, user
role, own-bot exclusion and both original millisecond time boundaries before
calling the native codec. Group mentions require exact bot open-ID metadata;
quoted roots, display names, user-ID aliases and @all do not grant access.
This function consumes already authenticated bytes; it does not authenticate
webhooks or sockets by itself.

The actual Lark model and pinned Hermes normalizer produce text, rich posts,
mention/command handling and resource descriptors without a client, download or
local file write. Header/body snapshots and current grant hashes are checked
again; private credential reflection is refused. Image/document, audio and video
permissions remain separate even when the native SDK labels a video resource as
`file`. Rich-post tags and duplicate resource keys require all corresponding
owner approvals. The real SDK fixture reproduced and caught the initial video
consent mismatch; fixed fixtures retain their negative assertions.

This is still a private codec/admission stage. Authenticated transport, durable
capture/dispatch, actual resources/voice, replies and owner GUI remain unfinished.


Private original-event custody now commits bounded immutable bytes before the
native input receipt. An opaque reference keeps large UTF-8 originals out of the
64 KiB native payload field. Full-synchronous SQLite/WAL, physical/logical quotas,
current-publication callbacks and source/credential/codec hashes protect replay.
Changed transport delivery IDs retain the first original; changed message bodies,
old credential epochs, damaged proofs and revoked grants are refused. Real SQLite
quota and in-transaction authority-withdrawal faults preserve previous records.
No original is automatically purged. Close/reopen tests cover commit gaps; they
are not a real machine power-cut acceptance.

The retained text bridge runs the actual pinned Feishu decoder under an exact
native claim. It uses canonical app open IDs even when upstream prefers user-ID
aliases, binds account scope, bypasses volatile burst buffers in favor of durable
HAOS acceptance, and retains reply context after native payload compaction.
Actual relay/controller fixtures create a scoped mission and handle status and
cancel commands. A real relay-SQLite-full fault retains pending input and retries
without a second mission. Raw callbacks/cards/synthetic events and all unreviewed
connect/send paths remain denied in the standalone ingress guard; only the
prepared private profile below installs reviewed lifecycle/reply methods.
Quote API reads and media dispatch are not yet
connected. Transport authentication, publication/service identity and direct
controller invocation are explicit fixtures at this stage; no external messages
or installed acceptance are established.

Private SDK reads now have a closed transport boundary: only fixed-brand HTTPS
origins, tenant/app-token acquisition, bot-account lookup and an independently
approved exact message read are admitted. Native Lark request serialization,
authentication and response models remain in use. TLS verification stays on;
redirects, caller transport options, custom Host/framing headers, unregistered
bearer tokens, unsupported asynchronous transport and unbounded responses are
refused. Publication and grant callbacks are checked before and during reads.
HTTP errors retain finite authentication/rate-limit/transport diagnostics.
Token caches are namespaced by the full private credential identity and brand;
a cached token must also have been observed by the current boundary. SDK debug
records are redacted without propagating raw records to parent log handlers.
The actual native-SDK TLS probe covers trusted/untrusted issuers, account-cache
reuse, credential rotation, exact-message permissions, revocation, redirect and
401/429/500 responses, malformed/duplicate/nonfinite/oversize/truncated bodies.
Only fixture code substitutes API origins with loopback and trusts its temporary
CA. The read contract is now used by the kernel-authenticated account worker
below. It grants no message-write capability or public gateway activation.

The prepared account check also runs in a disposable private gateway subprocess.
Both parent and worker enforce the actual unprivileged gateway UID/GID without
supplementary groups. The fixed root-owned interpreter runs with `-E -s`, a
minimal environment, bounded stdin/stdout/stderr, CPU/address-space/file limits,
a hard alarm and kernel parent-death SIGKILL. Every boundary rereads the trusted
root publication; pending publication, wrong account scope, own-bot grants,
unsafe policy permissions and changed snapshots refuse access. Cancellation and
withdrawal kill and join the child. This action can obtain a tenant access token
and query bot information, but cannot send a message or fetch arbitrary URLs.
Its result confirms only an exact returned bot open ID: this API does not prove
the separately supplied tenant key, so `tenant_identity_verified` remains false.

`probes/probe_feishu_process.py` exercises the actual native SDK and verified
TLS with real root/gateway/agent UIDs in a guarded fresh Docker namespace with
network disabled. Only that fixture adds its CA to disposable trust stores and
resolves the fixed Feishu API domain to a loopback HTTPS server; production code
and endpoint constants are unchanged. It checks policy-file gates, false bot
identity, 401/429, cancellation, live policy withdrawal, denied agent access to
private credentials and a running worker's input, and actual parent-death
SIGKILL with process reaping. It is not an installed service or owner GUI test.
Feishu remains outside the public registry until its transport, deliveries,
media, recovery and owner setup are connected and verified together.

A private fixed `/feishu/webhook` HTTPS receive application now verifies fresh
exact timestamp/nonce/signature headers against the actual pinned Hermes
validator. Case-duplicated signature headers, wrong mandatory verification
tokens and signatures, stale deliveries and unknown owner routes are refused.
Encrypted events use the actual Lark SDK AES decoder after signature validation
and strict canonical base64/body bounds. Signed, token-verified URL challenges
create no sender authority or mission. The application rejects insecure HTTP,
query routes and compressed request bodies, bounds concurrent body reads and
volatile source/rate budgets, and returns finite errors without private data.

Before a successful event ACK, authenticated wire bytes (including original
ciphertext), nonce identity and immutable independent approval are committed in
a private bounded FULL-synchronous SQLite journal, followed by original/native
input custody. Native decoding and mission dispatch remain independently
replayable. Reuse of a nonce with different bytes cannot replace a receipt.
Previously retained authenticated originals can recover after a commit gap and
live freshness expiry, while new stale requests stay refused. Quota exhaustion
and policy withdrawal leave existing receipts intact; there is no automatic
owner-data deletion. Verification/encryption secrets and the TLS key are
registered with redaction before native text projection.

The native webhook probe uses actual signatures, independently generated AES
ciphertext, the real Lark decoder, native Hermes message dispatch and verified
loopback HTTPS. It checks duplicate raw HTTP headers (a raw TLS request avoids
HTTP-client header normalization), unknown senders, nonce conflicts, physical
SQLite quota and a real SQLite-triggered storage failure followed by reopen and
freshness-expiry recovery. The prepared profile below now owns the private
long-running listener lifecycle. Owner publication/GUI, socket transport,
outgoing messages, media and owner recovery integration remain necessary
before public activation.

The prepared webhook profile now enforces the actual private gateway UID,
fresh root publication, exact timed account grants, an exclusive kernel profile
lease and immutable native credentials. Activation requires an installed durable
handler, verified owner TLS material and a successful no-send private bot check.
It binds only the fixed HTTPS receive route, with decompression disabled, and
replays authenticated retained originals/native inputs in a bounded background
loop. Policy withdrawal closes the listener; close cancels/reaps tasks and
releases the lease while retaining journals. Persisted finite account/TLS/rate/
storage/source statuses do not expose private exceptions. Each prepared profile
currently needs its own listener port; shared Feishu HTTPS multiplexing and
socket-mode integration are not claimed.

The expanded real-UID process probe checks actual profile creation, duplicate
lease refusal, native HTTPS input→durable relay dispatch, remote replay and
listener shutdown after an actual root policy replacement. All SDK/API targets
stay loopback in a disposable network-disabled namespace. The public factory,
owner GUI and public root publication still reject Feishu; this private profile
alone is not an activated complete gateway.

Private outgoing text/Markdown replies now use the actual pinned Hermes send
formatter, post codec and SDK reply builder. The original independently admitted
message, current binding digest, exact chat/native topic, body, native payload
and stable UUID are sealed together. One durable intent permits at most one
native reply API write. Native retries, post-to-text retry, top-level fallback,
changed UUIDs and alternate reply paths cannot escape that capability. The
separate reply boundary reuses verified fixed-domain TLS, bounded responses,
redaction, private observed token cache and fresh root/grant checks; the original
read boundary still grants no writes.

The private worker accepts only closed account/reply actions. A reply source
must match the current owner route and approved original bytes; its output is
only confirmed native acceptance, a finite definite rejection, or uncertainty.
A successful receipt needs exact native message/chat identity and the approved
topic when present. It does not prove recipient reading. The publisher joins
committed native input to retained source context, checks originals and writes a
FULL-synchronous intent before launching the worker. Confirmed receipts suppress
replay; body/source/authority changes conflict. In-flight/uncertain outcomes
remain quarantined across publisher reopen and later attempts. There is no
blind resend after a dropped response. Physical journal limits preserve older
receipts and require owner recovery rather than automatic deletion.

Actual HTTP/native-API rate-limit rejections create a persistent account pause,
shared across deliveries with the same private account. Reopening the publisher
or changing the delivery ID does not bypass the pause. Authentication refusals
remain blocked for that credential identity. Known pre-write transport failure
can retry within the bounded outbox attempts; unknown write outcome cannot.
Media output is explicitly refused until the separate private byte path exists.

Evidence includes native formatter/builder fixtures, real native SDK writes to
verified loopback TLS (drop/429/redirect/missing source/invalid-post fallback),
and real UID/profile/worker/SQLite cases: confirmed replay suppression, changed
body denial, uncertain reopen/later-attempt suppression and persistent account
backoff on a native rate code returned with HTTP 200. These are fixture replies
only, never external Feishu delivery or live-account acceptance. Actual process kill during an outgoing write is now verified below; complete
public owner adjudication/recovery still needs frontend integration. Public Feishu activation remains off.

The native private process probe now withholds an API reply after receiving a
write, verifies the committed `writing` intent through a separate read-only
SQLite connection, and sends actual SIGKILL to the gateway process. Its worker
also dies through the kernel parent-death guard and is reaped by the disposable
init. A new gateway process reopens the same profile, quarantines the in-flight
intent and preserves previously confirmed receipts without another API write.
The fixture waits for the real account pause to expire and signals readiness
before measuring SDK startup/write progress; it does not edit clocks or the
pause journal. This is a process-crash test, not a power-loss or installed OS
acceptance. Native connect/disconnect status writes now run inside the private
profile HOME context rather than falling back to the service's global HOME.

Offline private recovery exposes bounded delivery/account metadata without
message bodies or credentials. An exact inspected snapshot, current connector
read authority, authenticated-owner handoff, evidence hash and explicit
independent non-delivery confirmation are required to mark a private attempt
`owner-retry-approved`. The immutable decision is idempotent; confirmed native
acceptance, changed snapshots and ambiguous confirmation are refused. It sends
nothing and does not clear account pauses or change the controller obligation.
The separate controller UID must reconcile that outbox itself. Feishu delivered
adjudication accepts only its own native message-ID format. Neither operation
is exposed through model/transport RPC. Public owner command/GUI wiring remains
open while Feishu is disabled.

The SDK-free offline probe exercises actual root/agent/gateway/controller UIDs
and their separate ledgers in a disposable network-disabled namespace: denied
wrong-role helpers, private inventory, stale/confirmed-state refusal, idempotent
gateway approval, separate controller retry, and exact native receipt validation.
Owner policy, initial ledger states and service-stop control are fixtures; this
does not claim a graphical owner session or real external delivery inspection.

The private WS frame guard now keeps the actual Lark protobuf parser, fragment
assembler, dispatcher and ACK encoder behind bounded frame/header/fragment
limits. Missing required protobuf fields, duplicate headers, cards, invalid
sequence/count aliases, changed partial assemblies and excessive aggregate data
are refused before dispatch. At most 32 partial messages/16 fragments per message
are retained for five real seconds. Peer configuration cannot create a zero-delay
ping loop; partial valid configuration preserves existing safe defaults.
Incoming SDK dispatch runs inline with receive backpressure rather than spawning
an unbounded task per frame. The SDK thread waits for the actual owning loop's
SQLite capture and requires an explicit opaque durable receipt; that internal
receipt is not returned in the ACK. Storage failure returns native SDK 500,
while successful ACK follows original/native input commit. This guard still
needs authenticated endpoint discovery and actual WS TLS/profile lifecycle;
its probe uses a fixture socket sender and does not establish socket identity.

The frame probe uses actual native protobuf/assembly/ACK and pinned Hermes input
normalization with real private SQLite, an actual SDK-to-owner thread handoff,
real fragment TTL expiry and a real SQLite-triggered storage failure. Fixture
corrections retained assertions: native protobuf needs SeqID/LogID; the fixture
ACK inspector itself must also inspect SQLite on its owning loop, rather than
reading the connection from the simulated socket thread. SQLite thread checks
remain enabled. Public Feishu registry/GUI remains disabled.

The private native WS discovery guard now confines the actual SDK's AppID/
AppSecret POST to the selected fixed Feishu/Lark HTTPS endpoint. It requires an
explicit private connection scope, verifies TLS, refuses HTTP redirects/errors,
limits response bytes/deadline, validates native configuration and admits only
returned WSS URLs under the selected official brand. Caller URLs, userinfo,
alternate ports, ambiguous query IDs, unsafe paths and plaintext WS are refused.
Native SDK URL parsing and HTTP model decoding remain in use. Actual WSS uses
verified TLS, bounded messages/queues, disabled compression and no redirects;
caller proxy/TLS/socket options cannot override those limits. Only the SDK's
module aliases are wrapped, not the process-wide requests/websockets modules.
Native WS diagnostics retain severity without raw payload/URI/exception text.
Endpoint URLs and opaque query capabilities are registered for redaction;
public device/service routing IDs are deliberately not credential values.

The actual SDK discovery/WSS probe checks verified loopback HTTP and WSS,
Native protobuf→original/input SQLite→actual wire ACK, untrusted WSS issuer,
HTTP/WSS redirects, status errors, malformed/oversized endpoint data, withdrawal
and diagnostic secrecy. A goal containing digit `1` and restoration of its
opaque original prove that public routing ID `service_id=1` does not poison
redaction or input receipts. Brand origins, allowed fixture hosts/ports and CA
trust are changed only inside this disposable contract probe. This probe alone
does not establish kernel UID separation, process supervision or a live account.
The public registry/GUI remains disabled.


The prepared private profile now also supports native WebSocket mode. A fixed,
root-owned SDK worker runs under the private gateway UID, with a private home,
parent-death SIGKILL, bounded startup, address space, file descriptors and frame
queues. The parent checks fresh root publication every 100 ms and kills the
worker on withdrawal. No caller command, endpoint, proxy or TLS override crosses
this boundary. Shutdown makes the generation inactive before waiting for the
child; a late event cannot acquire input authority.

The native SDK receives success only after the independent parent has admitted
the exact original bytes into the FULL-synchronous original, reply-context and
native input journals. The parent checks canonical base64, checksum and strict
sequence; it returns only an opaque durable receipt. Failure, unknown senders,
withdrawal or unavailable storage produces no successful acknowledgement.
Ephemeral endpoint tickets stay inside the worker; normalization there refuses
reflection into goals or resource names before parent admission. SDK stdout is
separated from the private receipt protocol and stderr is discarded boundedly.

The pinned Hermes native WS runner and actual SDK remain responsible for
connection and native frame encoding. Hidden SDK reconnect is disabled: the
profile creates a new supervised child after a persisted 2–60 second backoff.
Authentication and TLS refusals stop automatic reconnect; rate refusal retains
a 60-second deadline. Original-event and NativeInbox identity survive disconnect,
process restart and duplicate delivery; reconnect never resends an outgoing
reply. The account check precedes initial activation, and the same independent
native decoder and durable RelayInbox path serves both HTTPS and WS profiles.

These are private integration paths. Public owner configuration, media/voice,
source disposal/recovery UI and final gateway activation remain unfinished.
No live tenant, external delivery, installed-system or hardware acceptance is
claimed by these loopback SDK/process fixtures.
