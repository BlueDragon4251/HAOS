# SMS / Twilio — prepared transport, integration still in progress

This is not a public HAOS gateway setup path yet. The ordinary policy/menu still
rejects SMS. `PreparedSMSPolicy` and the explicit private factory let the actual
pinned Hermes adapter be tested while media, owner setup and recovery are finished.
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

Remaining work before public setup: separately approved MMS/media paths, actual
owner CLI and GUI, service lifecycle/recovery inspection and decisions, full
negative/reconnect/crash/UID proofs and current CI. Provider accounts and recipient
handsets are only needed for the later real acceptance, not this implementation.
