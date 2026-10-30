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
retained paged history and replay, incoming/outgoing media and local voice,
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
