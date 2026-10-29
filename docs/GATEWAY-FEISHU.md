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
transport, bounded single-write replies, media/voice and complete owner
GUI/recovery integration remain open.
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
connect/send paths remain denied. Quote API reads and media dispatch are not yet
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
