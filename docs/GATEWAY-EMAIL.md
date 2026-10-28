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
closed actions currently permit account probing, bounded header reads and
received-date-filtered UID searches only. Account values travel in
private stdin rather than argv or environment; result/error schemas exclude
provider bodies and credentials. This is not yet a message-processing service.

Remaining: durable UIDVALIDITY/cursor handling with authoritative INTERNALDATE,
independent sender/thread admission before body/media use, bounded persistent
attachments/local voice, native SMTP write intent and recovery, credential
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
