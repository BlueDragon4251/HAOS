# SMS / Twilio owner setup and bounded MMS integration

SMS is now an explicit public HAOS owner setup path. The actual pinned Hermes
adapter runs only behind the independent HAOS timed sender grants and private
profile. Owner CLI/GUI, native media/voice composition, recovery and process/UID
proofs are implemented; local fixture success is not external acceptance.
No external SMS, account authentication, charges or recipient acceptance are
claimed by the local fixtures.

The implemented prepared path uses a dedicated Twilio Account SID/auth token and
an owned E.164 receiving number. Credentials and the HTTPS private key remain in
the gateway identity. Private fixed-origin, verified-TLS account/number reads
must confirm the active exact account and SMS-capable number before listening.
No arbitrary URL, proxy, redirect, shell or runtime installer is used for these
reads. HTTP cookies are disabled. Sender/chat are the same exact E.164 number;
scope is the exact account and receiver, with a timed owner grant and no threads.

The public webhook is exactly `/webhooks/twilio`. Strict bounded form parsing
rejects duplicate keys and malformed encodings before the actual pinned Twilio
signature validator. Unknown signed senders get no lookup, reply or mission.
A valid signature alone does not timestamp a Twilio webhook: the private message
resource must also match account, SID, sender, receiver, original body, inbound
state and creation time strictly after the current owner grant. Twilio timestamps
have second precision, so the grant's own second is conservatively rejected.
A committed message SID is replay-idempotent and cannot inherit a changed grant.
The durable inbox is committed before success; the actual native webhook decoder
then runs in a retained context into the independent HAOS relay. Unresolved
inputs keep their backoff/retry state instead of becoming untracked agent tasks.

The actual pinned SMS formatter, form builder and sender operate behind an exact
single-request capability and durable write intent. Root queue parts use the
1600-character SMS bound. A success needs an exact returned message/account/
sender/receiver/body receipt; it indicates server acceptance, not handset delivery.
Confirmed or ambiguous same-attempt writes do not repeat. Explicit rate refusal
pauses the profile, including after private profile close/reopen; account/identity
refusals likewise require owner recovery. The owner GUI and `gateway retry-sms-auth CONNECTOR` permit an audited
recheck after correction; they preserve throttling and uncertain writes.

LINE and SMS can share one HTTPS port when owner-approved certificate,
key and bind consent agree. Their fixed handlers and signatures remain separate;
removing one registration does not stop the other. Different public hostnames
can select distinct registered profiles when the same certificate covers them.
No native health, owner-policy or plugin endpoints are exposed. Plain HTTP remains
limited to earlier private LINE fixtures; published owner setups require TLS.

`probe_sms.py` exercises the actual adapter, native auth/signature/formatter codecs,
private REST, durable SQLite and verified loopback HTTPS. Its CA, resources and
endpoints are explicit disposable fixtures. `test_gateway_sms.py` also runs with
no Hermes source in PYTHONPATH. Current source-bound evidence is in
`docs/evidence/2026-10-28/sms-prepared-transport-validation.json`.

MMS supports separately approved private PNG/JPEG images, bounded
documents, audio and MP4/3GP/3G2 video. Empty-body MMS uses the actual native decoder
only after original signature, private resource and current grant checks. URLs
from webhooks are never fetched. Media is read from exact authenticated parent/SID
resources; one HTTPS redirect to the reviewed Twilio CDN hosts is allowed without
forwarding account credentials or cookies. Partial, encoded and oversized responses
are refused. Audio remains private for transcription and is never attached raw to
the model. `probe_sms_voice.py` verifies real local transcription, replay, invalid audio and
mid-transcription grant withdrawal; its speech RPC and agent terminal are explicit
composition fixtures, with actual UID/socket isolation tested separately.

Outgoing completed-session artifacts use the same bounded controller export and
grant-bound HTTPS capability service as LINE. The actual pinned native SMS sender
adds only checked MediaUrl fields for supported MMS; other files and SMS-only
numbers receive expiring download links. Revocation immediately blocks downloads.
`probe_media_backend.py --sms` also verifies exact incoming PNG, 500 KB document,
3GP and 3G2 bytes through actual native attachment RPCs.
`probe_sms_output.py` exercises the actual authenticated Hermes backend, completed
fixture session, controller export, native sender and HTTPS file reads. It does
not run model inference or contact an external Twilio account.

A private filtered message-list sweep recovers missed webhooks, one bounded page
per current sender grant every 30 seconds. Pagination stays within the exact
account resource and unchanged sender/receiver/date filters. A persisted cursor
advances only after durable admission or an explicit bounded refusal receipt; every recovered message is independently
verified against its exact private resource and grant epoch. Admission records
explicitly distinguish authenticated API recovery from a signed webhook. Repeated
sweeps reuse the message SID instead of creating another mission. Unsupported
content keeps a private, inspectable refusal receipt rather than starving later
supported messages. The last API recovery success/failure and next retry are
reported separately from listener readiness; a ready page does not prove complete
remote history. Offline private
auth recheck and receipt inspection are implemented internally; they preserve rate
limits, revoked grants and ambiguous writes, with owner audit context.

The public protocol reference used for media limits, message timestamps, resource
identities and filtered pagination is `twilio/twilio-oai` commit
`d9775142962ea67d5f3d50c5021a23ae6d330c5b`,
`spec/json/twilio_api_v2010.json`. This is API-schema evidence, not live acceptance.

## Owner operation

Use the graphical Gateways page or `haos-owner gateway setup CONNECTOR sms`.
Supply the exact Account SID, protected Auth Token, owned E.164 receiving number,
unprivileged local HTTPS port, public `https://hostname/webhooks/twilio` URL,
private certificate-chain/key PEM files and listener bind address. A public bind
requires explicit consent. The number's Twilio Messaging webhook must use POST
and the exact public URL. DNS, valid certificates and router forwarding are
operator prerequisites; saving does not send a message or verify reachability.

Then pair an exact E.164 sender: sender and chat must be the same number; the
account/receiving scope is derived from saved credentials, and thread is empty.
Select mission/status/control rights explicitly. Images/documents, voice, video
and outgoing result files each have separate initially unchecked approvals.
Voice additionally requires the reviewed local speech service/model. A phone
number grant is not independent proof of the human holding that number.
Restart the gateway service after setup/pairing. Credentials or listener changes
withdraw prior grants and require fresh pairing, while owner/recovery data remain.

Inspect retained ingress, profile status, file caches and ambiguous outgoing
attempts through the existing owner recovery page/console. `gateway ingress`
and `gateway deliveries` use unprivileged ledger helpers. Authentication recheck
never sends a message or clears throttling, revocation or ambiguous write intent.
A confirmed hash receipt is server acceptance, not handset delivery. Explicit
owner reconciliation requires the inspected attempt and platform-specific proof;
retry needs confirmed non-delivery. Never retry an uncertain push automatically.

`probe_sms_delivery_process.py` installs normalized public code into a fresh
network-isolated Docker namespace, uses real gateway/agent UIDs, performs verified
HTTPS ingress/media/send, kills the gateway with SIGKILL while its write is pending,
then verifies lease reacquisition, retained input bytes and no duplicate send.
The agent receives no credentials and cannot open private journals or owner files.
Root publication and media/voice consent tests run with the shared strict TLS
owner fixture; GUI tests cover 1280x800 and 640x480.

External account/number provisioning, provider/carrier MMS availability, real
handset delivery/playback, public DNS/router reachability, installed HAOS service
and HP acceptance remain separate. No production account or phone is used by
these fixtures. Current source-bound evidence accompanies each increment under
`docs/evidence/2026-10-28/`.
