# Photon integration in progress

Photon is **not yet an accepted HAOS gateway**. The accepted local software
count remains 16/22. The pinned Hermes adapter and its Spectrum 12.7.0 Node
sidecar are the integration target; listing the plugin is not completion.

Photon provides managed iMessage transport. It does not require the Owner to
operate a Mac relay. Actual account entitlement, a provisioned project, assigned
line and external delivery require a later account-specific acceptance. Shared
lines cannot initiate arbitrary new conversations. The pinned SDK exposes no
receiving number in shared mode: independent authority is bound to the project
and explicit `shared` mode, never to an inferred receiving line.

## Prepared transport boundaries

`runtime/prepare_photon.py` verifies the exact Hermes sidecar, package manifest,
committed npm lockfile and published Spectrum iMessage codec before applying
reviewed embedding hooks. No input change is accepted silently. These are
build-time inputs, not an instruction to install dependencies in the service.
The production gateway is not activated by this preparation alone.

The early SDK hook runs before message, poll or group mapping can hydrate
remote content. A second sidecar hook checks the resolved source before
normalization and requires durable custody before NDJSON dispatch. Embeddings
can supply a private listener and must authorize both request routes and bodies.
An incomplete embedding fails closed. Standalone upstream behavior remains
available only when no trusted embedding is supplied; HAOS still needs to wire
its fixed launcher and process boundary before public activation.

The embedding can suppress automatic contact sharing and quoted-message
hydration. Reply bodies and immutable target IDs are preserved without fetching
quoted content. Mixed attachment groups remain one native source, preserving
their original message GUID. The bounded reader uses the actual SDK attachment
stream, checks current authority between chunks, enforces declared and actual
length, cancels failed/hung streams and never calls the unbounded `read()` path.

## Prepared independent policy and custody

The prepared policy requires exact Apple sender addresses, native chat GUIDs,
project/phone scope, fresh timed grants and exact threads or explicit whole-chat
approval. iMessage, SMS and RCS service selection is explicit. Missing senders,
display aliases, automated/self messages, ambiguous chats, old events, mismatched
SDK cursors and unknown services do not establish authority. Attachment, local
voice, video and outgoing-file consent are separate from mission capabilities.
Unsupported eager vCard conversion is currently refused before downloading.

The private SQLite store retains the first raw source before native conversion
and the independently checked normalized body before dispatch. It uses FULL
transactions, bounded capacity, immutable source and credential/grant mappings,
byte lengths/checksums, replay checks and a single parent custody receipt.
Withdrawal and damaged/purged originals cannot silently gain fresh authority.

The private control component now uses an AF_UNIX listener with a fresh launch
token and actual SO_PEERCRED checks for the supervised child PID/UID/GID. Wrong
processes cannot use another process's token. Refusals retain only a bounded
reason/hash record; failed writes and withdrawn policy produce no custody
receipt. Existing socket paths are preserved rather than unlinked blindly.

The actual prepared Spectrum mapper, native sidecar normalization functions and
Hermes Python adapter are connected in a component probe. It covers text,
replies, group threads, mixed image/text, files, audio files, native voice notes,
CAF MIME aliases and retained replay. The checker preserves the pinned SDK's
exact part ordering, child IDs and JavaScript whitespace rules. At most four
attachments are accepted. A scoped native cache transport supplies only opaque
retained media IDs; native temporary host paths never become agent inputs.
Transferred cache rows replay without restoring their acknowledged bytes.

Native receive cursors now have their own FULL SQLite record. An SDK-prefetched
candidate cannot advance the restart point past an unfinished original. Once
the normalized source is durable, a separate native inbox and the actual HAOS
RelayInbox take responsibility for controller delivery. Restart recovers these
decoded sources without requiring another SDK event. A lost parent receipt
after a real relay commit retries the same durable identity, preserving one
relay row. The codec/ingress probe now covers 18 cases, including database reopen
and that ambiguous receipt.

The prepared actual Spectrum resumable stream accepts a durable initial cursor
and awaits cursor persistence before advancing its own cursor. Cursor rejection
invokes the embedding's explicit recovery gate, preserving the original failure
instead of falling back silently to live events. The initial cursor zero asks
for available history; a server that no longer retains it requires inspected
Owner recovery. Ordinary nonembedded SDK behavior remains available unchanged.
The HAOS embedding also disables automatic SDK RPC retries; actual write/RPC
failure behavior still requires the forthcoming native transport fixture.

The fixed Node embedding disables inherited telemetry,
automatic read receipts, contact sharing, implicit URL fetches, typing/reactions
and unapproved writes. The prepared private profile connects that embedding to
the actual SDK, Unix receive stream and durable inbox. It remains outside the
public registry until outgoing replies and Owner management are complete.

The image build now installs the exact official Node 24.19.0 archive and the
committed Spectrum lockfile with dependency lifecycle scripts disabled. It
records thirteen actual program digests, including the bounded cloud transport.
The private launcher verifies those
digests, immutable root ownership and canonical paths, uses fixed arguments and
a restricted environment, and never invokes npm in the service. Public program
directories are made readable by the actual service identity during installation;
private account/receive stores are separate.

An offline disposable installed-layout fixture passes 17 actual process/kernel
checks: exact UID/GID, root/agent/supplementary/saved-ID denial, changed source,
writable/hardlinked/foreign-owned program rejection, required NoNewPrivileges,
withdrawal during startup and hard parent loss. The actual production bootstrap
is used, with its first private resume RPC held before SDK initialization. The
actual SDK resume probe also passes under the private UID using immutable
installed modules. A second fixture now exercises the actual native connection:
seven checks cover verified TLS/HTTP project authentication, the actual protobuf
gRPC services, unknown-sender refusal, approved message admission through the
native SDK/sidecar/Python codec, duplicate suppression, parent receipt and cursor
persistence, and immediate Owner withdrawal of the running Node process.

That fixture runs under the actual private UID in a network-disabled disposable
container. Only SDK endpoint literals are changed to local peers, and a fresh
test CA is installed using the regular system trust mechanism. No TLS verification
is disabled. Two fixture assumptions were corrected: protobuf-loader service
names are PascalCase, and the fully wrapped SDK supplies the exact provider name
`imessage`. The independent projection checker now requires that actual name;
the invented `iMessage` component fallback is explicitly refused. Native proxy
`spc-*` message IDs and exact `any`/`iMessage`/`SMS`/`RCS` chat GUIDs follow the
pinned protocol without aliasing different identities.

The complete connection also exposed a socket creation race. The fixed Node
bootstrap now sets a private umask before listening, so the supervisor cannot
observe a transient nonprivate mode before the listen callback changes it.
Current-authority checks remain required. Recorded finite status and stable
account retry budgets are persisted atomically; later network errors cannot
replace an earlier terminal authentication/revocation reason. This is recorded
local state, never proof of live account entitlement or recipient receipt.

The bounded cloud transport is now wired into the actual SDK before module
initialization. It permits only the three required project/token/platform
operations against the fixed HTTPS origin, refuses redirects, bounds response
bytes and total fetch time, and reports finite status without native error
bodies. Actual gRPC error codes follow the same private status path. The
supervisor stops the process and enforces persistent retry budgets instead of
letting internal SDK retries race the independent authority.

Both the initial token catalogue and actual SDK token renewal pass through
exact approved-line selection. Shared/dedicated mode mismatches, missing or
ambiguous dedicated numbers and unsafe instance host labels are refused before
client creation. Other project lines are filtered before opening channels.
Private account credentials cannot select arbitrary hosts or program paths.

Ten complete private-UID TLS/gRPC scenes pass 54 checks: shared and dedicated
receive/revoke paths; HTTP 401, 403 and 429; actual gRPC authentication and rate
errors; wrong dedicated line; and actual token-refresh 401/429. Reopening a
profile cannot bypass a terminal refusal or a current account budget. Eight
additional cloud-boundary component checks cover fixed routes, redirects,
response bounds and typed errors. A late generic startup error retains an
active rate-limit diagnostic. Changing service toggles cannot turn the same
refused project key into a fresh credential; old prepared status rows remain
intact and their refusals are carried forward.

## Prepared source-bound replies

Text replies now use the actual Hermes Python send formatting, native sidecar
and Spectrum reply builder. The retained source GUID supplies the reply target;
quoted message contents are not fetched. After restart the embedding resolves
an exact existing space reference through the SDK's pure `space.get` constructor,
avoiding the upstream fallback that can create a dedicated-line chat.

The private outbox requires completed original/native/parent custody, the exact
current Owner route and controller content/event identity. It stores a one-use
capability hash bound to recipient, source, thread and native body. The real
child must consume that capability through its PID-authenticated control
socket, and SQLite must commit `writing` before any vendor RPC is allowed.
Changed recipients, body, source, expired/replayed permissions and failed
consumption writes cannot reach the native send operation.

A confirmed vendor acceptance ID is returned from durable history on a repeat
call or process restart. A consumed write without an acceptance receipt stays
uncertain across attempts and reopening; it is never automatically resent.
An unconsumed permission can be atomically cancelled, preventing its late use
and permitting a subsequent controller attempt. Vendor acceptance is not proof
of recipient delivery or reading. Both SDK middleware retries and the underlying
gRPC channel's transparent retries are disabled for the trusted embedding.
Standalone nonembedded upstream behavior is preserved.

Implicit URL/file fetches, media writes, polls, edits, deletion, typing and
reactions are refused at their method boundary pending their own reviewed
capabilities. A plain text reply cannot turn into a rich-link fallback or an
arbitrary filesystem upload. Outgoing files still require a sealed media path
before public activation.

Native fixtures exercise successful replies, confirmed receipt replay and
actual Node/profile restart, refused SQL consumption, lost acceptance, Owner
withdrawal during an actual write, and real TLS connection loss after the peer
received the request while the peer remains available for a possible retry.
These use real SDK/protobuf calls to loopback; the controller event metadata
and final RelayInbox callback remain fixture inputs, not a controller inference
or external delivery claim.

The running Owner watchdog is separate from network health requests. A test
that stops the actual Node process with SIGSTOP and observes a blocked real
health coroutine still requires withdrawal within the original two-second
bound. The prior observer source fails that same test; the corrected observer
passes. Unexpected observer failures stop the child and clear local connection
state, including a publication revoked during an awaited health response.

## Evidence limits and work remaining

The local speech decoder now accepts CAF under the existing bounds and
pipe-only protocol allowlist. Actual encoded CAF preserves reference PCM and
is recognized by the pinned Whisper engine both directly and under the separate
Speech UID through checked controller Unix RPC. The old decoder rejected the
same valid CAF fixture. This closes a local format gap; the complete Photon
attachment RPC/controller/speech flow still needs its own native acceptance.

The native transport probe exercises the actual prepared Spectrum mapper and
its attachment-stream cleanup with local RPC frames. Python tests exercise the
independent policy and actual SQLite writes, failures and reopen behavior.
The Photon CI workflow runs these contracts without external messages. These
checks do not establish a live Spectrum connection, receipt by another person,
HAOS controller inference, installed service/GUI behavior or hardware acceptance.

Still required before counting Photon: full durable receive/replay/controller
path, broader reconnect/refresh and recovery acceptance, supported media
and voice conversion, inspected source/output/account recovery, real Owner GUI
and CLI onboarding/device authentication, build installation/provenance and
end-to-end native/private-UID fixtures. Continue this gateway before Raft,
SimpleX, Teams, WeCom and WhatsApp.
