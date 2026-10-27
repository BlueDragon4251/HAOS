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
The owner can inspect and explicitly purge controller payloads using the
physical setup's gateway media page or the root console, with execution stopped:

```sh
sudo haos-owner stop
sudo haos-owner media list
sudo haos-owner media purge --id EXACT_UPLOAD_ID --note 'Inspected unused upload' --confirm-inspected
```

The GUI stops gateway/mission services before inspection and leaves them stopped;
use the existing explicit runtime-start action afterward. Console operations
require gateway, controller and Hermes to be inactive with zero main/control
PIDs. The fixed offline helper opens the ledger as `haos-control`, never as
root, using the existing private-directory, owner, regular-file, single-link and
SQLite sidecar checks. A missing ledger is refused rather than created by the
owner UI. The child receives only exact IDs, owner UID and an inspection hash;
no raw note, transport/provider credentials or arbitrary database path.
Inventory includes all bounded active uploads and at most 128 recent purged
metadata rows; older tombstones and audit remain in the private ledger. Purge
refuses nonterminal missions and validates the whole bounded selection before
changing any bytes. It frees chunks/quota while retaining upload tombstones,
mission associations, owner audit and a transactionally committed purge receipt.
The confirmation is unchecked and resets on selection changes and submission.
This is logical payload removal, not physical secure erasure, and cannot erase
agent copies, backups or previously transferred content. Replayed old IDs remain
unusable, and a damaged/purged attachment never becomes a text-only mission.
The separate gateway-cache view opens its private journal only in the real
unprivileged gateway identity, using the existing fixed offline recovery helper.
It never hands that journal to the agent or changes its owner to root. Cache
cleanup requires a withdrawn/changed sender grant **and** explicit inspection
confirmation; current grants cannot lose their pending bytes. The helper stores
an atomic owner UID/note-hash decision and a tombstone, so an old grant cannot
silently download/reintroduce the removed payload. A newly approved grant uses a
new media ID. Existing retained signed inputs are preserved; use their separate
owner recovery path if they need an explicit discard decision.

```sh
sudo haos-owner gateway stop
sudo haos-owner gateway media-cache
# Withdraw/change the selected sender grant before cleanup.
sudo haos-owner gateway purge-media-cache --id EXACT_CACHE_ID --note 'Inspected revoked input' --confirm-inspected
```

The graphical media page links both independent stores. Cache inspection stops
only the gateway; controller inspection stops mission services as described
above. None of these operations restarts services automatically. Voice/video
and outbound media remain open.

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
