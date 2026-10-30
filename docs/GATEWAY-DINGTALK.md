# DingTalk — private integration in progress

DingTalk is not in the public HAOS gateway registry or owner GUI. Twelve public
software paths are listed in [Gateways](GATEWAYS.md). SDK presence and the private
contracts below are not a complete gateway or live-account acceptance.

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
agent goals. Incoming resource retrieval and sealed mission dispatch are still
separate pending work.

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

Still required before public activation: shared controller mission acceptance, outgoing media and local voice
paths, stable reply capability after session expiry, owner account/per-write
and resource recovery/management,
source management and complete owner setup/GUI. These private transport pieces
must be connected to the independent shared mission and management boundaries.

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
