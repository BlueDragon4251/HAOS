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
relay row. The codec/ingress probe now covers 15 cases, including database reopen
and that ambiguous receipt.

The prepared actual Spectrum resumable stream accepts a durable initial cursor
and awaits cursor persistence before advancing its own cursor. Cursor rejection
invokes the embedding's explicit recovery gate, preserving the original failure
instead of falling back silently to live events. The initial cursor zero asks
for available history; a server that no longer retains it requires inspected
Owner recovery. Ordinary nonembedded SDK behavior remains available unchanged.
The HAOS embedding also disables automatic SDK RPC retries; actual write/RPC
failure behavior still requires the forthcoming native transport fixture.

The fixed Node embedding source is present and disables inherited telemetry,
automatic read receipts, contact sharing, implicit URL fetches, typing/reactions
and unapproved writes. Its production process installation, full live transport
and supervision still need to be connected and verified; source presence and
syntax checks are not an installed-service acceptance.

## Evidence limits and work remaining

The native transport probe exercises the actual prepared Spectrum mapper and
its attachment-stream cleanup with local RPC frames. Python tests exercise the
independent policy and actual SQLite writes, failures and reopen behavior.
The Photon CI workflow runs these contracts without external messages. These
checks do not establish a live Spectrum connection, receipt by another person,
HAOS controller inference, installed service/GUI behavior or hardware acceptance.

Still required before counting Photon: fixed private launcher installation and
supervision, full durable receive/replay/controller path, actual native guarded replies and
outbox, reconnect/rate/auth status, immediate process revocation, supported media
and voice conversion, inspected source/output/account recovery, real Owner GUI
and CLI onboarding/device authentication, build installation/provenance and
end-to-end native/private-UID fixtures. Continue this gateway before Raft,
SimpleX, Teams, WeCom and WhatsApp.
