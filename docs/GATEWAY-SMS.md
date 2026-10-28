# SMS / Twilio — prepared transport, integration still in progress

This is not a public HAOS gateway setup path yet. The ordinary policy/menu still
rejects SMS. `PreparedSMSPolicy` and the explicit private factory let the actual
pinned Hermes adapter be tested while owner setup and recovery integration are finished.
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
refusals likewise require owner recovery. The explicit recovery UI is still open.

LINE and prepared SMS can share one HTTPS port when owner-approved certificate,
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

Prepared MMS now supports separately approved private PNG/JPEG images, bounded
documents, audio and MP4/3GP video. Empty-body MMS uses the actual native decoder
only after original signature, private resource and current grant checks. URLs
from webhooks are never fetched. Media is read from exact authenticated parent/SID
resources; one HTTPS redirect to the reviewed Twilio CDN hosts is allowed without
forwarding account credentials or cookies. Partial, encoded and oversized responses
are refused. Audio remains private for transcription and is never attached raw to
the model. The SMS-specific voice composition proof is still open.

Outgoing completed-session artifacts use the same bounded controller export and
grant-bound HTTPS capability service as LINE. The actual pinned native SMS sender
adds only checked MediaUrl fields for supported MMS; other files and SMS-only
numbers receive expiring download links. Revocation immediately blocks downloads.
`probe_sms_output.py` exercises the actual authenticated Hermes backend, completed
fixture session, controller export, native sender and HTTPS file reads. It does
not run model inference or contact an external Twilio account.

A private filtered message-list sweep recovers missed webhooks, one bounded page
per current sender grant every 30 seconds. Pagination stays within the exact
account resource and unchanged sender/receiver/date filters. A persisted cursor
advances only after durable admission; every recovered message is independently
verified against its exact private resource and grant epoch. Admission records
explicitly distinguish authenticated API recovery from a signed webhook. Repeated
sweeps reuse the message SID instead of creating another mission. Offline private
auth recheck and receipt inspection are implemented internally; they preserve rate
limits, revoked grants and ambiguous writes, with owner audit context.

The public protocol reference used for media limits, message timestamps, resource
identities and filtered pagination is `twilio/twilio-oai` commit
`d9775142962ea67d5f3d50c5021a23ae6d330c5b`,
`spec/json/twilio_api_v2010.json`. This is API-schema evidence, not live acceptance.

Remaining work before public setup: actual
owner CLI and GUI, service lifecycle/recovery inspection and decisions, full
negative/reconnect/crash/UID proofs and current CI. Provider accounts and recipient
handsets are only needed for the later real acceptance, not this implementation.
