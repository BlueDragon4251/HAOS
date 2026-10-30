# Buzz — private integration in progress

Buzz is still outside the public HAOS gateway registry. The public software
count remains 14/22 after A2A. These prerequisites do not establish a working
Buzz mission, GUI, external relay, installed OS or release acceptance.

The actual pinned Hermes Buzz adapter uses the official Rust `buzz` CLI for
queries and writes, plus native NIP-42 WebSocket authentication and polling.
A list entry alone is insufficient. Its native channel discovery, cursors,
unsigned metadata assumptions, media paths and command process must remain
behind independent HAOS grants and persistent first-byte/operation custody.

## Implemented prerequisites

- Exact dedicated Nostr private identity with an explicitly expected public
  key, canonical HTTPS relay origin and one to 32 explicit channel UUIDs.
  Private keys may be canonical hexadecimal or nsec; native identity/checksum
  verification must occur in the private service before readiness is asserted.
  Optional NIP-OA owner-attestation input has a bounded closed shape. No
  caller-controlled CLI path, arbitrary plugin or implicit watch-all channel is
  accepted.
- Prepared independent sender/channel/relay-account/thread grants have fresh
  timed epochs and separate media/voice/video/output choices. This prepared
  policy deliberately does not add Buzz to the public GatewayPolicy or GUI.
- The official CLI source is fixed at
  `block/buzz@1eb67bb525d66448b56d79f98c4ba0e2188b44c5`, with exact archive and
  Cargo.lock digests, Rust 1.98.1 and a digest-pinned builder image. The native
  CLI does not implement `--version`; package/source provenance and actual
  executable digests identify the build instead.
- An exact-source constructor overlay disables HTTP redirects while retaining
  actual native NIP-98 signing, event construction, idempotent retry and response
  handling. No authentication or process-global HTTP hook is replaced. The
  overlay validates all source/lock inputs before mutation and fails on drift.
- The offline signature verifier uses official `nostr` 0.44.7, not a custom
  Schnorr verifier. Its 107 dependency identities/checksums are a checked subset
  of the exact official CLI lock. Its frozen build succeeds. The fixed helper
  accepts at most 1 MiB, returns only validity/event ID/public key and does not
  echo parser errors or event content.
- The private Python boundary validates finite signed-event fields, refuses
  duplicate JSON identity keys, uses only root-owned single-link fixed program
  paths and checks executable bytes against installed provenance. Actual helper
  execution requires the real gateway UID/GID without supplementary authority;
  requests, output, deadline, environment and process cleanup are bounded.

## Actual local evidence so far

Ten cross-codec cases exercise actual pinned Hermes NIP-42/BIP-340 signing and
compiled official Rust SDK verification, including UTF-8 message/tag integrity
and negative signature/digest/shape/size cases.

Six actual CLI/verified-loopback-TLS cases exercise NIP-98 URL/method/body/nonce
binding, real signed-message construction and acceptance receipts, definite
429 replay of the same signed event, persistent 401 refusal, redirect refusal
and post-body disconnect. A reconnect inside one native CLI invocation retains
the exact same signed event ID/body. Exhaustion reports `delivery_unknown` with
`retryable:false`; this is not authorization to start another signing process.
The relay and CA in this fixture are local test boundaries, not a live account.

Nine disposable installed-code process cases exercise the compiled SDK under
the actual gateway UID. Root/agent UID and supplementary-root-group calls are
refused; writable, changed, multiply linked or symlinked programs are refused.
Actual unprivileged identities cannot alter program/provenance files or read
an owner canary. These checks use real kernel identities and files, not mocks.

## Outstanding before public activation

The complete native adapter lifecycle, authenticated WebSocket boundary,
integration of retained history into live dispatch, incoming/outgoing media and local voice,
independent root mission/control dispatch, delivery/uncertainty recovery,
owner account/discovery/pairing/recovery GUI, installed image packaging and
build/CI wiring still need completion and source-bound evidence. No permission
or completion is inferred from the successful prerequisites above.

## Native WSS and durable original work (still private)

The pinned Hermes preparation now adds a per-instance `_open_websocket` hook
without changing native challenge signing, subscription construction, dispatch
or cursor code. The private transport refuses redirects, pins the selected
relay/public identity/challenge/attestation, restricts channel/membership filters,
checks the current publication around I/O and bounds frames, queues and input
rejection. Unknown senders do not trigger native username/media work or receive
an implicit HAOS identity. Unsolicited “seen” reactions are not authorized output.

The original-custody boundary verifies actual Nostr signatures before native
cursor mutation, binds exact channel/thread/epoch/account, checks independent
mention/media choices and retains the first canonical signed event in FULL
SQLite. Nostr signature randomness is not a new semantic message: replay keeps
the first valid original signature. Local native and parent-relay receipts do
not claim root mission admission. No purged original is silently restored.

The actual CLI now accepts a narrowly scoped read-only composite cursor through
`HAOS_BUZZ_BEFORE_ID`, paired with the exact `--before` timestamp and unchanged
channel/since bounds. It uses the official relay's existing `before_id` query
field. This prevents the native 50-event window from being mistaken for complete
catch-up when several messages have the same timestamp. Durable page/recovery
integration still needs completion.

A real UID/WSS/native-MessageEvent fixture exercises native NIP-42, signed CLI
userinfo lookup, source custody before dispatch, local inbox/relay reopen,
unknown sender and channel refusal, redirects, auth refusal and root-owned
policy replacement. It is not a complete production profile or controller
mission test. Eight actual CLI/TLS/cursor cases also pass.

The first real CLI call under the disposable UID exposed a build ABI mismatch:
the default Rust 1.98.1 slim builder required glibc 2.38 while the pinned Python
process fixture has glibc 2.36. The same Rust version now uses the digest-pinned
Bookworm builder; both resulting programs require at most glibc 2.34 (verified
from ELF version records). Dependency versions, signature checks, actual UIDs
and assertions were preserved. The native dependency tree is installed with
its real package permissions for the private UID; inaccessible host-venv paths
are not treated as an SDK/product failure.

The expanded actual UID/WSS/custody fixture now passes eleven cases. Eight
signed negative inputs cover signature, stale/future time, mention, thread,
private-key reflection and voice approval. It also changes signature randomness
for the same Nostr event ID, injects a real SQL acknowledgment failure after
local inbox/relay commits, closes/reopens the journals and verifies exact
reconciliation without another admission. Damaged retained bytes are rejected
without silent restoration. These are local receipts; controller missions and
production profile recovery remain a separate unfinished integration step.

Source-bound evidence for this stage is in
[evidence/2026-10-30/buzz-native-custody-validation.json](evidence/2026-10-30/buzz-native-custody-validation.json).

## Fixed read process and persistent history (still private)

The private Reader now runs the exact root-owned, digest-checked official CLI
under the actual gateway identity. Its closed read grammar refuses writes,
arbitrary flags, unknown peers/channels, unbounded queries and injected stdin.
It checks the native private-to-public identity before any query, strips ambient
credentials/proxies/program overrides, uses the installed system CA, bounds both
output streams/deadline and kills the process group on cancellation or withdrawn
owner publication. Authentication refusal remains sticky in this reader.
Discovery results expose only explicitly selected channels. Relay error bodies
never become native mention-retry instructions, logs, or fake empty history.

History uses a FULL private SQLite checkpoint bound to the exact account and
current timed grants. Each step requests at most 50 signed events with the
official composite timestamp/event-ID cursor; every admitted original must be
durably retained before the cursor transaction can commit. Reopen resumes the
saved tuple. The completed scan retains an inclusive five-minute overlap for
permitted clock skew/late arrival; event custody absorbs replay. Capacity errors
halt advancement rather than discarding sources. This is complete local paging
against the fixture relay's contract, not a promise about an unavailable or
noncompliant external relay retaining messages indefinitely.

Actual source inspection also found `cmd_get_messages` converted malformed JSON
into an empty history with `unwrap_or_default`. The exact-source overlay now
changes that parser to a finite error. No other command parser or native signing
behavior is replaced. The actual rebuilt CLI verifies this over HTTP/TLS.

Sixteen actual installed-UID/CLI/WSS/custody/history cases pass, including 121
events sharing one timestamp across three pages and fresh process reopens,
a real SQL cursor failure after fifty durable originals, exact page replay and
malformed HTTP history without a false completed scan. Nine separate actual
CLI/TLS cases pass. These do not establish full profile/controller/media/GUI
integration, outbound delivery or public activation.

## Private native text profile (still outside the runtime factory)

The private profile now combines the actual pinned adapter's NIP-42 connection,
bounded Reader, guarded WSS, FULL originals, history and independent native
inbox. One actual kernel lease covers a relay/public identity across connector
IDs. Its home, credentials, channel set, publication and grants are pinned;
native plugins, unsolicited reactions, arbitrary writes and media shortcuts
remain unavailable. A live monitor checks publication even when the relay is
idle and closes the native socket/tasks after withdrawal. Authentication and
identity refusal survive a process restart; rate limits have a finite cooldown.

The actual native decoder produces MessageEvents from retained signed sources.
Its first command projection and exact native mention-normalizer inputs are
retained before local parent admission. A later display-name change cannot
alter an already accepted command. Original signed content remains separately
available for verification. Local/native receipt gaps are reconciled against
their original source and grant; a lost settled receipt is not silently rebuilt.
Media sources remain pending for the forthcoming media implementation, without
being downgraded to text or reported as accepted missions.

Twenty-one disposable process cases now pass, including actual root/foreign UID/
supplementary-group factory refusal without optional SDKs, compiled CLI retries
of exactly three read-only 429 queries with fresh NIP-98 nonces, native command
projection replay, SQL failures on both sides of local admission, private
identity lease enforcement, an idle socket closed by a real root-owned policy
replacement, and authentication refusal across fresh UID processes. Minimal and
full regressions each pass 2,537 tests with the same two existing skips; 172
actual root/kernel cases pass.

These are private component/profile and local parent-relay receipts. The public
runtime factory, root controller mission flow, outputs, media/voice, owner GUI,
recovery decisions, image packaging and CI wiring remain unfinished. Buzz is
still not counted as the fifteenth completed gateway.

## Signed outbound custody and private outbox (still not public)

The reviewed CLI overlay now bounds actual HTTP response headers/chunks before
JSON allocation (8 MiB success, 64 KiB error), rejects invalid UTF-8, and refuses
definite 401/403 before parsing an opaque response body. Native read retry and
NIP-98 signing remain intact. Fifteen actual CLI/TLS cases pass, including the
size/encoding limits and a private prepublication handshake.

The actual native message builder/signature is retained. Before submission, a
scoped Unix socket sends at most 1 MiB of its signed event to the private gateway
process and requires an explicit one-byte acknowledgment. The gateway checks the
real CLI peer PID/UID/GID, verifies the actual official SDK signature, checks the
sealed body/channel/thread/recipient/resource choices, and commits the signed
original before acknowledging. Denial or disconnect before acknowledgment never
falls back to unguarded publication. Output, environment, process deadline,
current authority checks and process-group cleanup are bounded.

The private Publisher now binds an exact outbox attempt to a committed original
input and the current independent read/reply grant. It invokes the actual pinned
`BuzzAdapter.send`, permitting only one native write with the approved target;
native mention fallbacks cannot launch an extra publication. Confirmed attempts
return their existing event ID. A crash or lost local acceptance commit leaves
an uncertain attempt; it never automatically starts a new signing process.

An inspected stopped-profile recovery decision uses a current grant, exact
snapshot, explicit non-delivery confirmation and an audit record. An approved
next attempt reuses the retained signed event through an actually sealed memfd.
The native SDK verifies the inherited event and keeps its timestamp, signature,
content and ID; the same prepublication checks still apply. This private helper
is not yet wired to the public owner UID/CLI/GUI handoff.

Twenty-seven actual UID/CLI/WSS/history/profile/outbox cases pass. They include a
real SQL failure when saving acceptance after the fixture relay accepted the
event, fresh-process uncertainty with no automatic resend, refusal of a stale
owner inspection, idempotent recovery authorization and exact signed replay
through actual `BuzzAdapter.send`. The fixture relay checks committed signed
bytes before accepting HTTP. These are local relay acceptance receipts; they
do not prove recipient reads, live external delivery or full controller/owner
handoff integration. Minimal/full regressions each pass 2,551 tests with the same
two existing skips. Buzz remains private at 14/22 public software gateways.

## Retained incoming media and real local ASR (still private)

The native media GET uses Blossom kind 24242 (`t=get`, server and expiry), not
NIP-98. Its actual CLI signer is preserved. A further exact-source overlay bounds
binary success bodies to 8 MiB before allocation and uses the scoped native
request/connect deadlines; errors use the bounded common handler. Seven actual
CLI/TLS/Blossom cases verify signatures, binary bytes, redirects, declared and
chunked limits, definite 401, exactly three read retries and partial-body loss.

Signed source admission now distinguishes the relay's content-addressed media
namespace from up to eight explicitly approved foreign HTTPS origins. Private
identity is never sent to a foreign media origin; anonymous fetches use the
installed system CA, no ambient proxy/authentication, no redirects and bounded
bytes/deadline. An imeta URL repeated in the body is one resource. Separate
media/voice/video checks apply to actual byte classification, so an audio object
labeled as a generic file does not become a document capability.

Before download/dispatch, the first actual native mention/media-text projection
is retained. FULL first-byte resource receipts precede private blob insertion;
reopen may fill a genuinely missing insertion only with the same anchored hash,
MIME and descriptor. Existing damaged cache bytes are refused without refetch or
restoration. Native imeta and bare-reference handling receive only independently
retained opaque resources, then MessageEvents carry private media IDs rather
than host paths. Media control commands fail before credential spending.

Thirty-five installed-UID/native-process cases pass, including PNG, document and
voice admission, anonymous approved foreign TLS media, exact resource replay,
real SQL blob/parent failures and corruption, unapproved origins and voice
disguised as a document. The voice path composes the actual decoder, private
cache, controller functions and pinned offline ASR under the gateway UID with a
root-owned model. The expected speech reaches a text-only protocol terminal;
replay does not retranscribe or create another mission. Private speech IPC and
the terminal are explicit fixture seams, not an installed speech-service or
provider inference acceptance.

Minimal/full regressions each pass 2,565 tests with the same two existing skips;
172 actual root/kernel cases pass. Public factory activation, media outputs,
real owner UID/GUI recovery, production controller process integration and
packaging/CI remain separate unfinished work. The public count remains 14/22.

### Private sealed artifact uploads and native file replies (2026-10-30)

The reviewed CLI overlay now derives its additional generic-file MIME subset
from the exact pinned relay validator. This reconciles the relay's actual
PDF/document/audio support with the older CLI image/video-only list; it does
not update dependencies or admit the relay's blocked executable MIME types.
Native Blossom upload signing, primary/legacy endpoint selection and bounded
same-byte retry behavior remain upstream code. Files are nonempty and at most
8 MiB before reading; upload responses use the bounded strict native handler.

The private HAOS uploader accepts immutable bytes through a Linux-sealed
inherited memory descriptor, uses only the fixed installed CLI and its
`upload file --file` grammar, and verifies the actual stored blob through the
native authenticated media GET. A foreign descriptor, checksum/size mismatch,
credential reflection or unexpected generic-file transformation is refused.
Image/video normalization retains distinct source and stored hashes. A second
sealed descriptor carries up to four already verified uploads to the native
message builder. Its real imeta tags, content, filename, reply/thread and
notification recipients are checked before the signed original is committed
and publication is acknowledged. No file is uploaded again by message sending.

Buzz now uses whole-event controller output projections and exact root-owned
export snapshots. Upload intents are committed before network I/O. Successful
source/blob/descriptor custody is reused after process restart; unresolved
intents and damaged retained blobs stop for inspected recovery rather than
triggering automatic upload or restoration. A private owner recovery interface
for these upload intents is still required. The public factory stays closed.

Validation at this checkpoint: 2,601 tests pass with both the minimal and full
pinned runtime, with the same two existing skips; 172 actual root/kernel cases,
15 native CLI cases, seven native media CLI cases and 42 installed-UID process
cases pass. The additional output component cases explicitly substitute the
root export RPC; real controller projection/SQL contracts are exercised
separately for both A2A and Buzz. No installed controller-to-native-file flow,
GUI/account setup, external relay delivery, provider inference, release or
hardware acceptance is inferred from these fixtures. See
[evidence/2026-10-30/buzz-native-output-validation.json](evidence/2026-10-30/buzz-native-output-validation.json).

### Offline upload decisions (private component)

Unresolved uploads now have finite no-network inspection and recovery functions.
An exact snapshot, current account, unchanged outbound/read grant, explicit owner
identity and review-note hash are required before allowing a retry. Decisions
are audited and idempotent, advance the inspection snapshot, and allow at most
two additional upload operations. A previously consumed decision cannot release
another operation. Existing signed reply custody prohibits replacing its upload.
Payload disposal requires withdrawal/change of the original grant and retains
metadata, audit and tombstones; backup/WAL erasure is not claimed.

The installed-UID component probe now passes 43 cases, including a real SQL
failure after native upload and a new process consuming the exact approved
retry. Both runtime regressions pass 2,612 tests with two existing skips and
172 root/kernel cases pass. These component decisions are not yet connected to
an authenticated root owner worker, CLI or GUI; the probe's owner request and
root export RPC remain explicitly identified seams. See
[evidence/2026-10-30/buzz-upload-recovery-validation.json](evidence/2026-10-30/buzz-upload-recovery-validation.json).
