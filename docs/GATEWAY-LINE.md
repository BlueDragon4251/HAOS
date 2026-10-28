# LINE owner setup and bounded media integration

HAOS connects the actual pinned Hermes LINE adapter to independent timed owner
grants, private credentials, graphical/CLI setup, a verified HTTPS webhook and
persistent delivery/recovery. Text, incoming images/documents/voice/MP4 and
outgoing images/M4A/MP4/download links have implemented software paths.
Local fixtures use actual SDKs and loopback HTTPS; external LINE accounts,
recipient playback, public DNS/router reachability and installed OS acceptance
remain separate. Nine public text paths still do not mean nine fully accepted
gateways or all 22 integrations.

## Configure the real listener

1. Enable the Messaging API and webhook in the LINE Developers Console. Obtain
   the exact channel secret, channel access token and bot destination (`U` plus
   32 lowercase hexadecimal digits). Use a separate bot identity. Native bot-info
   lookup must confirm that destination before listening or sending.
2. Prepare a public DNS name and current system-trusted server certificate chain
   with the matching unencrypted private PEM key. The URL is exactly
   `https://hostname/line/webhook`, publicly on port 443. Public IP URLs,
   credentials/query strings in URLs, other paths and nonstandard public ports
   are refused. PEM input files must be regular, single-link, owner/root-owned,
   private (`0600`) and bounded (chain 16 KiB, key 8 KiB). The graphical importer
   requires the trusted local owner seat and displays no PEM bytes.
3. In owner management select **line**, enter destination, local HTTPS port
   (1024–65535), public URL and bind address. Load certificate and key separately,
   then enter the masked channel secret and token. A public bind (`0.0.0.0` or
   `::`) needs separate explicit consent. Loopback (`127.0.0.1`) is the default.
   CLI: `haos-owner gateway setup line-main line`; it uses protected secret
   prompts and private PEM file reads, with `PUBLIC` confirmation for public bind.
4. Configure the **host firewall** to permit the chosen local HTTPS listener port
   when public bind is intended. The shipped firewalld zone otherwise denies
   unsolicited ingress. Configure the router/TCP proxy to forward public port
   443 to that TLS listener, or a local TCP proxy for loopback mode. HAOS does not
   silently modify firewall rules, router settings, public DNS or certificates.
   Public binding alone proves none of these external prerequisites. CGNAT needs
   an independently reachable relay/tunnel/public address; no direct reachability
   through CGNAT is claimed. Do not forward plaintext into this HTTPS listener.
5. Pair each authorized sender before starting. Without a matching timed owner
   grant the connector remains inactive. For example:

   ```text
   haos-owner gateway pair owner-line line-main U<32 hex digits> C<32 hex digits> --identity personal --capabilities create read cancel answer pause resume
   ```

   Use the sender's exact `U…` ID; a direct chat must equal that sender ID.
   Groups use `C…`, rooms `R…`. The bot destination scope is derived from saved
   private credentials and checked against any supplied `--scope`. Bot self-
   authorization, other destinations and nonempty threads are refused. Group/
   room replies are visible to all members; only explicitly paired sender IDs
   gain mission rights. Display names and unknown senders never gain authority.
6. Start with the existing gateway service controls. Enable the exact webhook
   URL and redelivery on the LINE side. Perform the account/network verification
   yourself before relying on remote missions; local fixtures are not that check.

## Recovery and renewal

Signed requests reach committed private native input before HTTP success. Native
decode feeds the durable relay/mission engine; stored failures survive restart.
The outbound native push path journals intent before HTTP and keeps provider
acceptance separate from recipient delivery. An interrupted/uncertain send is
not automatically resent. Use owner input/output inspection and explicit audited
delivery decisions. A LINE receipt has the form `line_push_<64 hex digits>` and
does not prove that a recipient read or received the message.

After correcting channel login/destination errors, the graphical recheck or
`haos-owner gateway retry-line-auth line-main --note 'account corrected'` records
an offline owner decision. It preserves throttle deadlines, revocation and
retained inputs; restart must still pass actual native account verification.

Native outbound HTTP 401/403 also pauses the connector and persists an account
authentication block; 429 pauses it until the private stored Retry-After deadline.
Other unsent obligations retain attempt zero while the connector is not ready.
Sends, reconnect and close are serialized so another request cannot escape while
the listener is being stopped. These blocks survive profile reopen. An owner
authentication recheck cannot shorten a rate deadline; after correction/expiry,
fresh native bot verification precedes sending previously unsent replies. See
`line-outbound-block-validation.json` for the reproduced prior 401 defect and
actual HTTP/mission-outbox/reopen recovery cases.

Replacing credentials, listener settings or certificate material withdraws old
sender grants. Re-pair explicitly and restart; old events cannot inherit a new
grant epoch. Secret/PEM inputs clear after submission and context changes. A late
file-import result is discarded if its configuration context changed.

Expired certificates remain inspectable and replaceable in owner configuration.
They cannot activate a listener: trust, hostname, key and time are checked before
any connection attempt. Refusal persists as a safe TLS diagnostic through close/
disconnect rather than crashing all connector construction. Configure current
material, re-pair and restart. Existing private files with conflicting contents
are preserved and require owner recovery. Remove/revoke leaves retained owner
and recovery data intact; externally managed firewall/proxy rules remain the
owner's responsibility and should be withdrawn when retiring the listener.

## Evidence and remaining work

Source-hashed evidence is in
`docs/evidence/2026-10-27/line-owner-setup-validation.json`. Native fixtures run
actual pinned parsers, HMAC, bot-info/push clients, HTTPS, private SQLite journals
and mission/outbox code against loopback endpoints. A separate disposable root
run exercises real private PEM files, CLI publication/pairing, credential and
certificate changes, foreign UID denial, remove and audit. Its service-stopped
inspection and audit-directory relocation are fixtures, not installed systemd
or owner-seat acceptance. Tk cases use real controls with explicit backend
handoffs. Both full and minimal Python suites and the independent kernel/UID
regressions remain required; GitHub CI must be attributed to its exact SHA.

The additional `line-actual-uid-sigkill-validation.json` receipt covers four
actual process cases. Public HAOS code, the pinned native adapter and frozen SDK
are installed root-owned/read-only in a fresh disposable container. UID 65534
passes the production runtime identity guard, handles a signed HTTPS webhook and
commits its private relay, then performs a native verified-HTTPS push. A real
SIGKILL interrupts that request after the durable write intent. UID 65533 cannot
read/open the journals or owner canary. A new gateway process reacquires the
kernel lease, preserves the committed input, marks the old write uncertain and
does not repeat the push. CA registration and endpoint substitution are confined
to this network-isolated fixture; this is not an installed HAOS/systemd, public
network, LINE account or recipient test. Both provider CI runs require it.
The tightened agent-role fixture accepts only state/canary paths, with no
credential payload on its stdin; its rerun is recorded separately in
`line-agent-fixture-isolation-validation.json`.

Incoming PNG/JPEG images (2 MiB) and documents (8 MiB) now use the shared
[bounded media transport](GATEWAY-MEDIA.md), only with an explicit per-sender
`allow_media` grant and mission-create permission. The GUI offers a separate
unchecked option and clears pending consent on sender/chat edits or submit;
CLI uses `gateway pair --allow-media`. Remote filenames never select host paths.

Incoming voice uses the
[isolated local speech path](GATEWAY-SPEECH.md) with separate `allow_voice`
approval; the agent receives the transcript, not the raw audio.
Controller payload and separate private gateway-cache inspection/purge are
available through the owner GUI and CLI; cache purge additionally requires
withdrawal/change of the sender grant.
This integration does not claim all 22 gateways, real LINE accounts,
external message delivery, installed boot, hardware tests or final ISO/container/
APK release acceptance. No external test messages are sent by these fixtures.

Outbound-media groundwork now includes `haos.hermes_artifact`: bounded byte reads
from the authenticated literal-loopback Hermes API with a required durable
session ID. It never opens the supplied path on the controller host, follows
redirects, uses proxies or retries a request. Reads check the caller's current
grant callback between bounded socket reads and before returning bytes; responses
have an 8 MiB decoded limit and a 30-second deadline (5-second socket timeout).
The primitive does **not** itself authorize an outbound attachment. The connected
LINE path below adds independent output provenance, owner approval, durable
delivery and revocable public media serving.
`probe_artifact_backend.py` exercises the actual pinned authenticated HTTP API,
including an exact 8 MiB read, oversized refusal and unknown-session refusal.
Its persisted session is explicitly a database fixture, not a model turn.


## Video and outgoing results (2026-10-28)

Incoming video has a **separate**, initially unchecked owner approval:
`gateway pair --allow-video`, requiring mission-create rights. Existing
`--allow-media` image/document permission does not expand. Signed native video
messages download only from LINE's fixed content API, then pass through the
private resumable upload into the exact mission. MP4 bytes are bounded to 8 MiB;
a reported duration, when supplied, must not exceed two minutes. The actual
`file.attach` RPC creates a `.mp4` attachment inside the agent namespace. This is
a file attachment, not proof of model video understanding or frame analysis.

Outgoing results need **another separate** option, `--allow-outbound-media`,
requiring reply/read rights and configured public HTTPS. Both flags have real
GUI checkboxes, default false; sender/context edits and submit clear pending
consent. Re-pairing without the flags withdraws them with a new grant generation.
The agent is instructed to put each selected `MEDIA:/absolute/agent/path.ext`
on its own line outside code. Bare paths, quoted examples, JSON tool logs and
arbitrary remote URLs confer no export authority. At most four distinct files
are accepted per result/delivery. The pinned native extension catalog is checked
in CI; formats unsupported by LINE's media API use a download attachment link.

The controller independently requires that the path occurs in both the immutable
outbox part and the completed, uncancelled mission result, with a valid durable
source session, current exact grant and in-flight delivery attempt. It requests
bytes from the authenticated agent HTTP API, never opens that path on the host.
Private snapshots are checksummed and reused across restart/retry; a changed
agent file cannot replace an existing snapshot. Known credential reflections are
refused. The ledger permits 128 active output snapshots / 64 MiB, separately
from the 256 MiB incoming reservation budget. Owner media inspection/purge covers
both, preserving terminal missions and output/audit tombstones. An unresolved
pending/sending output cannot be purged behind an in-flight sender.

The gateway independently checks the current output grant, verifies every
bounded chunk/hash and stores a private byte-only copy. Incoming and outgoing
cached payloads share 64 MiB. URLs contain a random 256-bit capability, expire
after one hour and recheck the exact grant before each bounded write. Download
responses disable caching and support single byte ranges, with four concurrent
reads and bounded transfer time. The webhook listener exposes only its fixed
webhook and output-capability routes, with access logging disabled. No private
host path is served. Owner revocation/closure blocks further reads; already
received copies cannot be recalled. Expired derived gateway copies may be removed
automatically, while the controller's snapshot remains until explicit owner purge.
Owner cache inspection/purge includes output copies; purge requires withdrawal or
change of the sender grant, records an audit and prevents republishing that copy.

The actual pinned `send_image_file`, `send_voice`, `send_video` and text builders
construct one push containing at most five messages including the caption.
PNG/JPEG output images are bounded to 1 MiB (including LINE preview constraints).
Native audio uses M4A with a parsed bounded movie duration; native video uses MP4
and the pinned public fallback PNG preview. Other file types are download links,
not falsely labelled native voice/video. This integration does not synthesize
speech or transcode arbitrary formats. Agent tools may generate a supported file;
TTS service/provider entitlement remains its own setup requirement.

All media pushes retain the existing durable write-intent/remote-receipt rules.
Confirmed or ambiguous same-attempt writes are never resent; a real process
SIGKILL is tested for both text and native image output. Explicit rate refusals
permit a new bounded attempt, with distinct capability URLs. Failures before any
LINE send can be distinguished from ambiguous writes: owner delivery inspection
shows `media-export-unavailable` or `media-export-or-format-refused`. Inspect the
source file/size/format, local backend/session, output approval and HTTPS setup;
then use the existing explicit delivery recovery or create a corrected mission.
A purged snapshot is not silently recreated.

Validation and exact source hashes are recorded in
`docs/evidence/2026-10-28/line-media-output-validation.json`. These proofs include
actual native backend/LINE/HTTPS compositions, independent owner publication,
separate UID/kernel tests and GUI handoffs. A fixture-completed mission is never
represented as actual inference or external recipient acceptance.
