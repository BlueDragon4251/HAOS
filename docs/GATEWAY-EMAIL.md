# Email — prepared private transport, not public setup

Email remains absent from public HAOS setup until owner recovery and real owner configuration join the prepared receiving paths. Bundled upstream
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

Remaining: audited owner SMTP/mailbox recovery, credential
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
or a public owner setup path. This receipt describes that earlier increment; the receiving lifecycle below now connects full-body text. Media and public setup remain open.


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
These private receiving and reply components do not constitute a finished public email gateway.


Prepared SMTP replies now use the actual pinned native MIME builder and native
login/send_message/cleanup lifecycle inside the supervised gateway-UID worker.
Each reply uses the specific durably admitted source, not the adapter's mutable
last-thread cache. Current read/reply permission fixes the recipient and mailbox;
In-Reply-To fixes the source, References retains the approved root thread. Native
headers, Unicode body, stable per-attempt Message-ID and creation time are checked
before a single explicit SMTP envelope is admitted. Unknown recipient/header
changes and reflected account credentials cannot gain a send capability.

A synchronous-FULL SQLite intent precedes worker launch. Completed acceptance is
recorded as an opaque SMTP acceptance receipt, never a recipient delivery/read
receipt. Explicit server rejections have finite private diagnostics; temporary
rejection disconnects the profile and persists a retry deadline across reopen.
Connection loss or cancellation after a possible write remains uncertain. Both
confirmed and uncertain deliveries suppress further writes even if another
attempt is requested or the profile is reopened; changing a delivery's source,
body or authority is refused. A hard-killed parent also kills its private worker
through a kernel parent-death signal, verified with real UID/process termination.
Owner review/reconciliation and safe clearing of auth/mailbox fences remain to be
connected before public setup. These SMTP tests send only to disposable local
TLS fixtures, with no external account or mail delivery.

SMTP reply lines, multiline count and aggregate response bytes are bounded.
Only a complete validated remote rejection can release a write as rejected;
a local smtplib error such as an oversized response must remain unknown. Owner
authority is checked between response lines as well as commands. Native TLS
fixtures cover oversized single/multiline terminal responses after DATA.


Incoming MIME is now inspected inside the resource-limited private worker before
full bytes reach its parent. The parent rederives the exact manifest. At most
128 MIME parts, depth 16 and four attachments are accepted; nested attached
messages/archives are not expanded. Each file is at most 8 MiB, with PNG/JPEG
images limited to 2 MiB in aggregate. Audio needs separate voice consent, video
separate video consent, and all incoming files require create permission. Mixed
messages are refused as a whole if a part lacks consent. Attachments cannot
reinterpret exact body control commands. GIF/WebP and other binary files remain
documents under the existing PNG/JPEG model-image contract; unsupported video
containers are refused rather than silently omitted.

The original pinned attachment helper runs in a newly created private temporary
cache home, with canonical per-part filenames, only after all metadata and
permissions pass. The returned regular single-link files must stay inside that
context and match exact approved bytes. Only these newly created temporary files
are removed after copying; existing owner/recovery files are not touched. Original
filenames are recorded as hashes and never become host paths. Native dispatch
uses opaque media placeholders, then exact event-bound capabilities into the
existing durable private media cache and controller uploads. Acknowledged cache
bytes compact while replay metadata remains. The separate 64 MiB raw-source store
remains bounded and still needs audited owner inventory/purge integration.

Actual native MIME and relay now reach the real pinned agent backend through
image.attach_bytes/file.attach, including an 8 MiB document and a real encoded
MP4. No host path is sent to the backend. Separate email composition fixtures use
the actual pinned offline local speech engine and reviewed model: raw voice
remains outside agent file APIs, its transcript reaches the controller prompt as
text, replay does not transcribe again, malformed audio stays pending, and owner
withdrawal after ASR blocks transcript publication and prompting. The private
speech transport and agent terminal are fixtures in that composition; real
UID/socket service acceptance is a separate mandatory kernel gate. No inference,
external delivery, installed graphical setup or hardware acceptance follows from
these local contracts. Outgoing MIME files and owner CLI/GUI remain open.

Native compat32 SMTP can fold a long Message-ID after the header colon. The
receiving codec now canonicalizes only outer ASCII folding whitespace while
retaining exact identifier contents; multiple IDs and internal controls stay
forbidden. Actual pinned codec fixtures cover the folded native-builder form.

The shared private gateway client now encodes request frames directly as UTF-8
instead of expanding Unicode to ASCII escapes, and refuses oversized or nonfinite
JSON before connecting. The 131072-byte limit is unchanged. A real distinct-UID
controller/socket regression reproduces failure before the fix and transfers
32000 four-byte characters with an exact envelope digest afterward; LINE and
prepared-email peer-denial tests retain their real SO_PEERCRED checks.


Outgoing artifacts now enter the prepared private reply through the actual
controller export API and authenticated backend byte reader. Only standalone
MEDIA directives in the immutable completed mission/current outbox/source
session can export a file; no gateway process opens the agent's host path.
Offers/chunks are bounded, canonical and checksum-checked. The controller's
durable snapshot is reused if the original agent file later changes. Missing
separate outbound-file consent strips paths and publishes no attachment;
withdrawn authority rejects the old delivery before further reads.

The private worker receives a bounded newline-delimited JSON header followed by
exact binary snapshots, with current-authority checks between chunks and strict
EOF/hash/count validation. It materializes only canonical files in a newly
created private temporary home, invokes the actual native attachment encoder
and SMTP lifecycle, and seals the compiled MIME digest before connection. A
real gateway-UID fixture transfers four attachments including the maximum
8 MiB document, PNG, actual WAV and encoded MP4, verifies exact decoded bytes
and suppression of a confirmed replay. Account-specific server message-size
limits still apply. Older secured text-only confirmation fingerprints remain
valid; no journal history is rewritten or owner/recovery data deleted.

Cancellation during process creation is separately reproduced with an actual
child already started but its creation future still pending. The parent now
shields creation, obtains the real handle, kills and joins the child before
returning. The parent timeout covers creation and pipe feeding as well as the
network operation. The worker's kernel parent-death guard remains independent.
Outgoing TLS/mail accounts and completed mission/session state are fixtures;
these contracts do not establish external mail delivery. Audited recovery, raw
source inventory/purge and the full owner setup/GUI remain to be connected.
