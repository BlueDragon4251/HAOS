# Gateway media transport — private backend, integration in progress

The controller provides bounded byte uploads and native Hermes attachments.
Signed LINE input now connects the actual pinned image/file adapter and private
HTTPS content client to this path. The owner must explicitly approve incoming
images/documents for each sender/chat grant, using the graphical setup or
`haos-owner gateway pair --allow-media`. Existing grants remain text-only.
Voice, video and outbound media remain open; local fixtures do not establish
live account delivery or model inference.

The private gateway cache is bounded to 64 MiB/128 records. The exact native
callback carries opaque IDs rather than host paths. Current approval is checked
before downloads, every read/upload chunk and mission admission. Downloads keep
TLS hostname verification, disallow redirects and encoded bodies, enforce byte
limits and reject known credential reflection. A lost upload receipt resumes
from the controller offset. Temporary gateway bytes are compacted only after
durable mission acknowledgement; authoritative controller bytes remain retained.

## Boundaries and persistence

Only the peer-authenticated gateway socket accepts `gateway.media.begin` and
`gateway.media.chunk`. Ordinary owner/GUI/agent method dispatch cannot obtain
this interface by supplying a role or UID in JSON. The new independent kernel
probe deliberately makes the socket filesystem-accessible, then proves an
actual foreign agent UID is rejected by SO_PEERCRED before reading a frame.
The gateway UID cannot read the controller's private ledger and cannot gain
owner methods with forged UID-zero/role fields.

Every upload requires an exact current LINE sender/chat/bot grant, a timed owner
epoch, `create` permission and an explicit boolean `allow_media`. Existing grants
have no such approval and remain text-only. No field contains a host path or an
arbitrary download URL. The ID binds connector, grant digest, message envelope
and a strict descriptor (kind, format, SHA-256 and byte count). New grants cannot
adopt old uploads. Policy is checked again for each chunk, mission admission and
each native attachment transfer, including immediately before model dispatch.

Chunks are at most 48 KiB with canonical base64. Documents are bounded at 8 MiB;
PNG/JPEG images and their per-mission aggregate at 2 MiB, leaving room for base64
within the existing 4 MiB model-broker request cap. A mission accepts at most
four distinct IDs; private retained uploads reserve at most 256 MiB/1024 records.
Only the bytes/format/hash declared at admission can become ready. Known private
controller credentials in a byte payload are refused rather than altered.

Versioned media tables are additive in the existing private FULL/WAL mission
database. Uploads resume from a committed offset after reopen; repeated chunks
must match exactly. Partial uploads and unadmitted ready data expire after
24 hours for admission, while retained data remains available for owner
inspection. Capacity refusal does not delete existing owner/recovery data.
Management/retention controls are still required before calling the overall
media feature complete.

Mission creation and media association share a transaction. A wrong-message,
expired, changed or over-budget attachment cannot leave a partial mission or
route. Message replay must preserve the exact media set. Before prompt dispatch,
the controller verifies retained chunks and current owner authority. Missing or
damaged media cannot silently become a text-only mission. Attachment rejection
or revocation prevents the model prompt and retains the existing mission retry
budget; a started/uncertain model prompt retains the prior no-replay semantics.

## Actual native consumer

Images use the pinned `image.attach_bytes`; documents use `file.attach` with a
data URL and a fixed content/session-derived basename. No gateway path is sent
to Hermes. Native file references are checked and included in the mission
prompt. File bytes stay within the existing agent sandbox/owner filesystem
permissions; this does not add per-identity isolation to Hermes's shared cache
or erase copies already admitted before revocation. Vision analysis additionally
depends on the selected model and native capability routing; byte transfer alone
is not an inference claim.

`probe_media_backend.py` starts the actual frozen pinned Hermes server in fresh
private state, verifies its authentication and child identity, then drives the
HAOS controller's real upload/mission code and both actual attachment RPCs. It
checks decoded PNG pixels and byte-identical storage of an **8 MiB** document.
It performs no model turn. Separate real-WebSocket fixtures exercise the actual
controller dispatch order and rejection/revocation without pretending to be
live Hermes inference.

Build and both provider-contract CI runs require the native backend probe. CI
also requires the stdlib-only disposable process probe with actual UIDs 65532,
65533 and 65534, private ledger permissions and kernel peer authentication.
No foreign-UID, socket or credential check is replaced with a mock or new skip.

Exact source hashes and local receipts are recorded in
`docs/evidence/2026-10-27/media-controller-core-validation.json`. GitHub CI must
be associated separately with its exact commit. Neither fixture success nor
this backend increment is complete LINE media/voice, live account/recipient,
installed systemd/OS, hardware or release-artifact acceptance.
