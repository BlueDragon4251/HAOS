# Email — prepared private transport, not public setup

Email remains absent from public HAOS setup until ingress, persistent delivery,
media, recovery and real owner configuration are connected. Bundled upstream
code or a passing connection probe does not constitute a completed gateway.

The prepared account contract requires exact lowercase mailbox identities, fixed
IMAP/SMTP endpoints, verified implicit TLS or STARTTLS and the exact receiving
Authentication-Results service ID. Sender and chat must be identical; mailbox
scope is bound to account/IMAP endpoint/INBOX, with a timed owner epoch and an
optional exact root Message-ID. No wildcard or display-name authorization exists.

The actual pinned Hermes MIME/authentication helper runs only after HAOS checks
one sender/Message-ID and the first exact receiving-service result. Later injected
results and suffix-only service IDs cannot gain trust. The receiving server is
the domain-authentication authority: it must remove forged results for its own
service ID and prepend its own verified result. Domain authentication is not
independent proof of an individual person. These prerequisites must be part of
owner configuration; no public configuration path is enabled yet.

The first native decode pass disables attachment extraction, so unapproved MIME
parts cannot create local files or agent paths. Exact UID and raw/header/body
bounds are enforced. Persistent MIME/media admission is still open.

The native IMAP/SMTP clients authenticate over checked TLS. IMAP uses readonly
EXAMINE and bounded literals/lines, with closed read-only command shapes; STORE,
EXPUNGE and mailbox mutations are denied. SMTP connection probes authenticate
without MAIL/RCPT/DATA or message-write capability. Actual TLS and STARTTLS,
certificate-hostname refusal, oversized literals and authentication failures are
exercised with disposable loopback servers; no external mailbox is contacted.

A separate private worker runs only as the real gateway UID. Its parent enforces
bounded input/output, fixed root-owned runtime code, current root publication,
revocation monitoring, cancellation kill/join and a hard child deadline. Its
closed actions permit account probing, bounded header reads, mailbox state,
received-date-filtered UID searches and independently approved complete-message reads. Account values travel in
private stdin rather than argv or environment; result/error schemas exclude
provider bodies and credentials. The prepared receiver now joins these workers to durable native input and relay dispatch; public setup remains disabled.

Remaining: bounded persistent attachments/local voice, native SMTP write intent
and recovery, credential
redaction/rotation/status, actual owner CLI/GUI and complete process/replay tests.
No external account, SMTP delivery, installed service or hardware acceptance is
claimed by these fixtures.


The next increment adds exact INTERNALDATE/UID/literal verification over the real
native IMAP client, with same-connection UIDVALIDITY/UIDNEXT checks. The private
worker transfers bounded, checksum-verified headers and complete ordered search
results. A private journal starts at cursor zero, fences UIDVALIDITY changes or
UIDNEXT regressions without deleting receipts or automatically re-enabling, and
commits cursor/dispositions together. Every searched UID needs a durable outcome;
captured outcomes require an existing native input from the same mailbox, whose
scope proof survives payload compaction. Actual SQLite fault tests verify rollback.
These are receiving-service components, not yet the connected full-message inbox
or a public owner setup path. Full body/media and SMTP publication remain open.


The prepared receiver rechecks exact owner sender/mailbox/thread and server
INTERNALDATE before requesting BODY.PEEK[]. It compares the full-message headers
to their approved digest, rechecks epoch and policy in child and parent, and sends
large bodies as bounded binary IPC instead of giant JSON/base64 frames. Complete
messages remain in a private 64 MiB / 128-message SQLite custody store; the agent
receives no raw pathname or account credential. Capacity exhaustion retains the
cursor and reports storage failure. Owner purge/compaction is still pending.

Actual native MIME parsing and native dispatch feed durable input, private relay
and independent controller admission. Reply source context is retained before
input admission; replay after input compaction cannot create a second mission.
Authenticated body commands reach the exact controller parser without Subject
rewriting them. Unsupported oversized text or reflected private credentials are
explicit source refusals so they do not poison all later mail in a search page.
Attachments remain disabled until their separate custody and approval paths exist.

The prepared lifecycle supervises account connection, mailbox search/header/body
capture and replay, persists finite status and retry deadlines, fences mailbox
identity changes, and kills/joins workers on cancellation or owner withdrawal.
Same-credential authentication blocks and retry deadlines survive profile reopening.
A fresh disposable real-UID process fixture exercises the connected receiver
through native verified TLS into retained input and relay. Separate actual native
dispatch fixtures reach controller missions without inference or SMTP delivery.
This remains receiving-side implementation, not a finished public email gateway.
