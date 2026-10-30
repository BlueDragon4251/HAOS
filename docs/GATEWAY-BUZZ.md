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
