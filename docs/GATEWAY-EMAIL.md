# E-Mail gateway

## Current implementation (2026-10-29)

The public HAOS gateway factory, owner CLI and graphical setup now connect the
pinned native Hermes E-Mail adapter to independent HAOS authorization. Local
software contracts cover account configuration, reception, replies, separately
approved attachments/voice, persistent delivery and explicit recovery. External
mail accounts, actual recipient delivery and installed graphical setup still
require account/device acceptance; fixtures do not establish these outcomes.

### Set up a dedicated account

In graphical Gateway management select **email**, enter a canonical lowercase
service address and private account/app password, and specify exact IMAP/SMTP
hostnames, ports and `tls` or `starttls`. Plaintext is refused. The receiving
server must strip forged Authentication-Results for its own authserv-id and
prepend trusted results. Independently verify this and explicitly confirm it;
enter that exact authserv-id. Domain authentication does not prove a person.
OAuth-only accounts need a supported provider-issued app password; this adapter
does not invent an OAuth flow or accept an arbitrary plugin.

Save the account, then use **Gespeichertes E-Mail-Konto ohne Versand prüfen**.
This authenticates the actual private IMAP/SMTP clients with a bounded worker,
without MAIL/RCPT/DATA. Errors are finite and credentials never enter agent
configuration, command arguments, GUI metadata or audit logs. Changing endpoints,
connector or platform clears the password and trust confirmation. CLI equivalents
are `haos-owner gateway setup ID email` and `haos-owner gateway email-account ID`.
Use protected owner input; never put a password in command arguments.

### Grant exact sender authority

Pair one exact lowercase sender address; its reply/chat address must be identical.
HAOS derives the mailbox scope from the saved service address, IMAP endpoint and
INBOX, assigns a fresh timed grant, and rejects self-authorization of the service
account. A blank thread means only messages outside a root thread. An existing
conversation requires its exact root Message-ID, including angle brackets.
Unknown senders, other mailboxes and threads have no implied authority.

Select mission rights explicitly. Images/documents, local voice transcription,
video files and outgoing result attachments each have separate default-deny
consent. Inputs need create rights; outgoing files need read rights. Voice also
requires the reviewed local speech service/model. At most four attachments,
8 MiB each; PNG/JPEG aggregate at most 2 MiB. Result files use controller-approved
immutable exports and native MIME attachments, without public download hosting.
Changing the sender or connector clears media consent. Account/password rotation
withdraws old grants; explicit re-pairing gets a new epoch. Removal withdraws the
stored account without deleting owner/recovery history. Revoke an app password
at the mail provider as well when server-side credential revocation is needed.

### Recovery and honest delivery state

The read-only IMAP scanner retains headers/source proofs before cursor advance.
Changed UIDVALIDITY or regressed UIDNEXT fences reception. In the owner recovery
view inspect the exact scan snapshot before appending a new local scan epoch;
old cursors and receipts remain intact. Authentication recheck preserves these
fences, current grants and retry deadlines.

An interrupted SMTP write is uncertain and is never automatically repeated.
After independently verifying non-delivery, inspect and approve the private
SMTP attempt, then separately reconcile the controller outbox. Neither owner
decision sends a message; starting the service can perform the explicitly
approved later attempt. Confirmed SMTP acceptance suppresses replay and is not
proof of recipient delivery or reading. Revocation stops further authorized work.

The source-management page lists opaque private profiles and bounded metadata.
Pending/recoverable inputs cannot be purged. Explicit logical disposal requires
a terminal input decision or an unadmitted source with withdrawn authority, an
exact snapshot and separate confirmation. Metadata, audit and tombstones remain;
old replay cannot restore the selected BLOB. This does not securely erase SQLite
free pages, backups, controller state or copies held by recipients.

Validation receipts identify exact source files and distinguish actual native
clients/TLS, real UID/socket processes, GUI handoff fixtures and external tests.
The final activation receipt is in `docs/evidence/2026-10-29/`. No live mail,
installed OS, HP hardware or release-artifact acceptance is implied.

## Historical implementation notes

The following notes describe earlier secured increments. Their former
"prepared/not public" and unfinished-path statements are historical; the current
status and setup steps above supersede them. Original receipts remain tied to
their exact sources.

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
these contracts do not establish external mail delivery. The full owner
account setup and GUI remain to be connected before public activation.


Offline recovery now uses the stopped-gateway owner path and a separate
unprivileged gateway helper. Changed UIDVALIDITY or regressed UIDNEXT requires
inspection of the exact inventory snapshot and an explicit owner decision.
Recovery appends a new local scan epoch and atomically switches its pointer;
old cursors, receipts and decisions remain intact. Stale running journal objects
refuse further work. The next connection must independently verify server state.
Authentication rechecks preserve mailbox fences, withdrawn grants and retry
backoff; they grant no new sender or thread authority.

Source inventory contains bounded metadata and opaque profile identifiers,
never raw messages or passwords. Explicit inspected source disposal is permitted
only after a terminal input decision, or for an orphan whose grant was revoked.
Pending or recoverable inputs remain protected. Disposal leaves immutable
metadata and an audited tombstone; replay cannot repopulate the old source.
This is logical removal of the selected live-cache BLOB, not a promise to erase
SQLite free pages, backups or controller history. No existing owner data was
deleted during development; these tests use disposable ledgers.

An uncertain SMTP write remains blocked across reconnects and controller
attempts. Only an inspected owner decision, with independent confirmation of
non-delivery, can approve a later private attempt. The controller outbox requires
its own separate reconciliation under the controller UID. Neither decision sends
mail. Confirmed SMTP acceptance cannot be released this way and does not prove
recipient delivery. A real gateway-UID loopback test exercises the explicit
release followed by one new controller attempt, then suppression of its replay.
A separate network-disabled process test exercises gateway/controller UID
separation and rejects root and unrelated peer identities without optional SDKs.


Prepared graphical owner controls now display finite mail transport errors,
active and archived mailbox scan epochs, SMTP server-acceptance receipts and
independently confirmed private retry permissions. Selecting another attempt
clears consent; changing the connector after inspection requires a new snapshot.
The source-management page uses opaque private profiles and metadata only,
protects pending inputs, and asks explicitly before logical live-cache disposal.
Actual Tk probes exercise both 1280×800 and 640×480 layouts. Owner handoffs in
these GUI probes are explicit fixtures; distinct-UID ledger tests remain separate.

The prepared dedicated account form masks the password, separates IMAP and SMTP
hosts/ports/TLS modes, requires explicit receiving-server header-custody approval,
and clears secrets and consent after endpoint or platform changes and submission.
Its no-send account-check backend invokes the existing fixed native worker under
the gateway UID, with root-owned code, private stdin, no supplementary groups,
finite diagnostics and a 35-second deadline. The public platform registry and
runtime activation are still disabled while pairing and publication integration
are completed. The GUI probes do not establish a live account or installed setup.

The live process integration fixture now generates a fresh server `INTERNALDATE`
with an explicit +0200 offset. Its deliberately old sender `Date` remains a
counterexample; the admitted input must carry the recent server time. The
previous hard-coded 28-Oct-2026 13:00 +0200 receipt crossed the real 24-hour
NativeInbox expiry at 29-Oct 11:00 UTC: the two provider-contract jobs on
0ecad43 correctly left that fixture input `expired`, attempt zero, rather than
executing it. Expiry policy, the 25-second integration deadline, UID gates and
all delivery assertions remain unchanged. Timeout diagnostics expose only
finite profile status and state/attempt counts. Native lifecycle status writes
also use the private profile HOME rather than the global service HOME.
