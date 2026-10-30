# A2A — private integration in progress

A2A remains outside the public HAOS gateway registry and owner GUI. Public
software paths remain 13/22. These native/local contracts are not a completed
A2A gateway, live peer or installed-system acceptance. Exact controller/UID
component evidence is distinguished below from direct local parent fixtures.

The pinned Hermes adapter provides a stdlib JSON-RPC HTTP server, bearer-derived
peer identities, in-memory TaskStore, native MessageEvent dispatch, task Futures,
Agent Cards, JSON/SSE replies and task/push-config methods. The HAOS path is being
connected to those actual functions rather than treating SDK presence as parity.
No additional Python extra, dependency update or external account is needed.

## Implemented private boundaries

- Exact private tokens for named peers; no shared-token/IP/anonymous identity.
  TLS requires a trusted current hostname/certificate/key, an exact `/a2a`
  endpoint, a nonprivileged listener port and explicit public-listener consent.
  The actual native token comparer is used. Token possession never grants a
  HAOS identity: peer, context, server scope, timed owner grant and capabilities
  remain independently checked.
- The HAOS scope includes the authenticated peer. Identical client message and
  context IDs from different peers cannot collide in the shared HAOS inbox.
  Canonical contexts avoid aliases in the pinned native conversation filenames.
- Strict bounded finite duplicate-free JSON, supported send methods, roles and
  text-part codecs; native text extraction and untrusted-input framing. Keys,
  escaped variants, private TLS material, arbitrary profile routes, unreviewed
  callbacks and undeclared attachments cannot become a text-only mission.
- FULL/WAL original custody before native task creation. JSON-RPC correlation IDs
  and send/stream wrappers may change on retry; the first original body, source
  identity, account epoch and grant remain immutable. Changed or purged originals
  cannot be silently replaced/restored. A2A has no authenticated sender timestamp;
  its first authenticated server receipt is retained and replay stays bound to
  that original grant.
- Actual native TaskStore/task-ID/Future codecs with a separate bounded SQLite
  index. Native tasks bind one retained source, peer/context and owner grant;
  parent input receipts are separate. Concurrent duplicate sources create one
  task. State transitions have durable write intents; a failing final commit
  remains blocked after reopen. Terminal outcomes cannot be changed on replay.
  Only current grants are restored; retained old history is not deleted.
- Actual native prepare/MessageEvent/send/finalize/RPC paths through the HAOS
  durable dispatcher, without the separate model/plugin dispatcher. Fixed native
  local-agent routes and declared HAOS skills avoid ambient CLI profile/tool
  registration. Direct unretained events and changed post-custody parameters are
  refused. A native sender's timestamp-only success is insufficient: the exact
  task Future and committed result must match. Actual native email redaction and
  input-required transformations are tested, including replay of original text.
- Bounded real TLS front door around the native HTTP handler: 16 total connection
  slots, four active requests per authenticated peer, bounded handshake/header/
  body/response I/O, fixed Host/advertised endpoint and protocol versions. Native
  discovery uses its trailing slash; both exact `/a2a` and `/a2a/` POST endpoints
  are supported. No generic route/profile/proxy dispatcher is exposed. Private
  task reads/list/subscription check peer and current grant; pages are honestly
  capped. Native callback support is not advertised before its private transport
  is connected. Unauthenticated loopback callers receive no peer rights.
- Native submitted/working SSE frames arrive before a deliberately withheld final
  result. TLS stream drop, later result and GetTask recovery preserve one input.
  Disconnect/timeout does not invent failed HAOS missions. Current publication
  withdrawal closes listener, connections and native waiters. Concurrent cleanup
  shares one joined cleanup operation; TLS sockets are tracked before handshake.

## Still required before public activation

Complete public runtime/relay activation, clarification mapping, approved
media/voice/video and output-file paths, required callback transport, full OS
service-supervisor acceptance, inspected owner recovery, secure account/peer
management and the full graphical path. The controller/outcome and real UID/
socket components now covered are described below. A queue receipt must
not be mistaken for a completed task result. Every source-bound validation
receipt distinguishes real native/local work from substituted controller/IPC or
service supervision. No external messages are sent during development fixtures.

## Controller outcome integration (private)

Controller deliveries now carry a bounded, separately committed event context in
an additive outbox table. Existing gateway schema and chat transports retain
their behavior. Context corruption quarantines the delivery, records an audit
event and exposes a finite reason in owner recovery; it does not guess task
state from the message text. Only question ID/method are exported, not private
tool parameters. Queue and claim events never complete a native task, even when
they are collected after the mission has completed.

A private publisher retains individual chunks in FULL SQLite custody, checks the
complete ordered group against its original route/event digest and byte count,
and then resolves the actual native Future. Partial acknowledgments mean local
queue custody only. Replayed or out-of-order chunks cannot prematurely complete
a task. Exact controller completion, failure, cancellation and input-required
states have immutable per-event acceptance epochs. A question can be followed by
a final outcome; replay of the old question cannot replace that final outcome.
Failed epoch/group receipt commits can recover an already committed native
outcome without repeating native execution. This currently accepts complete text
outcomes up to 32,000 UTF-8 bytes; larger results require the still-pending bounded
artifact transport, never truncation presented as success.

The component probe uses actual MissionStore/GatewayEngine transactions and the
actual native MessageEvent/Future/finalizer. Its parent dispatch is a direct local
fixture, not the installed controller socket or gateway UID. Public activation,
full mission controls, media, management and GUI remain unfinished.

## Dedicated UID and controller socket (private)

The private A2A factory now requires the actual `haos-gateway` UID/GID before
SDK imports or credentials. It validates the saved root-owned publication,
retains separate per-peer HOME/task journals under a real exclusive kernel
profile lease, and uses the same native task/TLS transport on reconnection.
The wire client ID is bridged to the generated native task ID only inside a
verified active parent dispatch. A retained parent receipt survives process
loss; reconnect/replay never creates a second relay input or mission.

The actual process fixture installs public code as root, drops to the gateway
UID, creates a verified loopback TLS connection and forwards through the actual
Controller Unix client with kernel `SO_PEERCRED`. The controller's existing
policy callback selects the prepared A2A policy in this fixture; production
public registry/owner activation remains disabled. A foreign UID is denied even
when it has socket group access. Private accounts, journals and owner canaries
remain unreadable to that UID, and installed code remains unwritable. A real
SIGKILL/reopen restores working task state and later accepts an exact complete
multichunk controller result. TCP `SO_REUSEADDR` allows TIME_WAIT recovery;
`SO_REUSEPORT` is not enabled and competing processes still fail the kernel
profile lease.

Cancellation uses an immutable, source-bound local command intent and the
independent controller's `/cancel` path after receiving the task's exact mission
receipt. It checks the cancellation capability separately and carries the
expected binding digest to the controller; a changed owner grant cannot be used
in the interval between the transport check and root admission. A repeated
explicit cancel RPC retains the same controller deduplication identity after a
lost receipt. Its native response reports `haosCancelRequested`; it never
manufactures a cancelled task while the mission remains running. Only the
actual controller terminal event group may complete the native task/Future as
cancelled. Root admission, state collection and ACKs use the real bounded Unix
client. The fixture does not run model inference or the OS service supervisor.

The 13-case process contract is now mandatory in pinned-runtime CI. No external
peer, owner GUI, media/artifact/clarification completion, installed HAOS boot or
release acceptance is claimed from it.

## Exact clarification/approval continuation (private)

A continuation uses the existing native task ID and an immutable source-to-
question input journal. It does not create a new HAOS mission or replace the
original task/source mapping. Each actual controller question is exposed in
native JSON/SSE Task metadata as `haosQuestion` with `epoch`, `requestId` and
`method`. A client must send that exact epoch as
`message.metadata.haosQuestionEpoch` together with `message.taskId`; unrelated
metadata, a stale epoch, another peer/context/grant and a second source for the
same question are refused. Native wire IDs still deduplicate retries. These
metadata values identify the question; they grant no authority themselves.
The independent `answer` capability and current root binding epoch remain
required. Approval answers are exactly `once` or `deny`; permanent/session
approvals are unavailable.

The retained answer is translated into the exact controller `/answer` operation
inside the verified private parent-dispatch context. Actual native MessageEvent,
TaskStore, Future, JSON and SSE codecs are retained. A continuation's working
state describes processing/relaying that explicit answer; it does not assert
that the controller has accepted it or that the mission has completed. Later
controller question/final events resolve that same task. Native HTTP finalizers
are held behind the complete local task/outcome-epoch commit, so a question
cannot race the durable proof needed by its next answer. The pinned native
sender used under this lock only resolves a Future and contains no suspension
or network I/O.

A real closed Hermes WebSocket leaves the answer unconfirmed. Its native task
requires owner inspection (`haosQuestionUnavailable` and
`haosAction: inspect-owner-console`); no fresh question token is invented.
Replaying the original source, or inventing a new wire ID, does not re-send that
uncertain answer. The 19-case offline process contract now exercises actual
Controller/HermesConnection WebSocket requests and responses, numeric question
IDs, successive clarification/approval epochs, early continuation SSE, exact
`once`, stale/permanent denial, final result and real transport loss. It runs
with the actual dedicated gateway UID, root Unix client and SO_PEERCRED gates;
there is no agent inference, live external peer or full installed service test.

Repeated admission derives private wire aliases only from fixed account material,
not recursively from the previous aliases. Five hundred actual codec replays
prove stable bounded retention while raw/private-PEM and both supported escaped
forms remain refused. Per-peer logs use the dedicated private profile HOME;
process status files require the separate launcher-home fix described below.
Outgoing artifacts, automatic voice transcription, complete owner
recovery/configuration and GUI, required callbacks and public activation remain
outstanding.

## Incoming media and private first-byte custody (private)

Native inline `raw` file Parts and native/legacy URI file Parts now reach the
actual adapter builder. The native one-MiB request bound remains in place;
larger attachments use the separate bounded HTTPS file read (up to eight MiB
per file, four files per message). URI downloads require exact owner-approved
HTTPS origins for the named peer. There is no credential forwarding, cookie
reuse, redirect following, downgraded scheme or generic local-path loader.
Signed URI capabilities remain only in the private original; actual native
text extraction/logging receives an opaque file carrier. Agent-facing media are
limited local capabilities, never the signed download URL.

Generic media, automatic voice input and video each require separate timed
create grants. Known audio/image/video bytes cannot be renamed as a generic
document to bypass their consent kind. Exact PNG/JPEG and ISO MP4/3GP types are
checked; voice remains voice and is never silently turned into a text-only goal.
The first complete response is committed in private FULL SQLite custody before
any cache or relay receipt. Failed cache copies and process reopen reuse those
first bytes, even if the remote URI has changed. Transferred cache receipts do
not silently restore consumed data. Refusals/backoff survive reopen; partial
responses do not become files. Native receiver coroutines and stalled HTTPS
reads are cancelled on withdrawal without manufacturing a failed/cancelled
mission or deleting original recovery data.

The expanded process fixture uses actual installed code, gateway UID, TLS
resource reads, private media relay, root media/mission Unix methods and kernel
peer credentials. Four original byte streams (PNG, document, reviewed FLAC and
actual frozen-codec MP4) arrive unchanged at the controller. Early native SSE
precedes the withheld file body. URI replay does not re-fetch or create another
mission. Missing consent, 401/429 and withdrawal during a stalled read are checked.
These are byte-routing/retention tests, not ASR, model inference, native-device
playback or live-peer acceptance.

Recovery now selects only native WORKING inputs. Native TaskStore creation
commits SUBMITTED before native anti-loop/readiness checks, so treating that
intermediate record as a dispatch permission could race a later rejection.
The actual sixth-turn rejection remains rejected after private recovery polling
and creates no root mission. Five preceding queued test missions are cancelled
by the fixture's configured root owner through actual owner dispatch; the test
does not bypass the active mission's shared agent-home lock.

Hermes deliberately uses the process home for its background status writer;
context-local peer HOME overrides do not select that file. The actual runtime
and standalone A2A factory now prepare `/var/lib/haos-gateway/launcher` under the
verified service UID before native imports. The process fixture waits for the
real status JSON and verifies its UID and private parent permissions. The older
clarification receipt did not assert background status-file placement; the
28-case media/process receipt provides that additional evidence. A separate
23-case component fixture covers native file codecs, first-byte SQLite failure/
reopen, strict origins, MIME/credential refusal and real HTTP faults.

### Private outgoing artifact path (2026-10-30)

Completed controller groups can project explicit file markers into actual native
A2A file Parts. The root controller reconstructs and verifies the whole immutable
chunk group before selecting markers: fenced examples remain text even across
chunk boundaries, repeated markers select the first snapshot only, and paths do
not reach the peer. Separate current read and outbound-file approval is required
before the authenticated agent HTTP reader is called. Without file approval,
the text includes an approval notice and no artifact URL is generated.

Exact bounded root export offers/chunks become private SQLite blobs tied to the
original source, task, owner grant, credential epoch and result group. An artifact
is unavailable until that exact native task outcome has a committed acceptance
proof. JSON and SSE completion/replay use the actual native file codec. The
approved HTTPS listener serves only opaque artifact IDs to the same current
named peer, with fresh authorization during the write, no-store/nosniff and
attachment headers. A durable local writing/completed/interrupted audit records
bytes written; it never asserts that a remote person read them.

The 33-case installed UID/controller/TLS fixture covers the actual root export
reader against a controlled loopback agent-file HTTP endpoint, whole-group
projection, native file Parts, completed SSE replay, unauthorized/wrong-peer
refusal and exact TLS bytes. It does not establish the actual upstream agent
filesystem/session handler or live peer acceptance. A separate nine-case native
component fixture covers real SQLite insert failure/retry, unfinished task
refusal, immutable metadata/group replay, blob/acceptance-proof corruption,
interrupted write accounting, current owner withdrawal and real database/native
TaskStore reopen. Both are executable checks; the component probe runs in build
and protocol CI. A2A remains private and the public gateway count stays 13/22;
long-output handling, ASR composition, callback/owner setup and full activation
remain outstanding.

### Complete long text and actual local voice composition

A completed controller response exceeding the native 32,000-byte reply limit
becomes a separate bounded UTF-8 text artifact (up to 8 MiB), plus a short native
reply. It preserves the complete projected response after the actual pinned
native egress redaction; it does not truncate the response or raise native RPC
frame limits. A text artifact requires the existing read grant, while agent
filesystem attachments still require separate outbound-file approval. Up to four
filesystem attachments and one complete text result can coexist. Whole-event
marker projections are retained atomically once and selected by indexed chunk;
large replies no longer reparse the entire event for every output chunk.

The expanded 34-case actual UID/controller/TLS fixture downloads a complete long
Unicode text result under a read grant without outbound-file approval, verifies
its exact bytes and verifies that no additional agent-file read occurs. Four
additional root-controller SQL tests cover cross-chunk fences/long Unicode,
rollback after a real projection-insert failure, changed retained proofs and
current grant withdrawal. The native controller probe now has 13 cases,
including complete long Unicode text and native email redaction.

A separate six-case A2A voice probe now composes actual native MessageEvent
preparation, verified HTTPS audio retrieval, retained-media relay, controller
execution and the actual hash-pinned offline ASR model. It verifies the reviewed
recording's transcript reaches the prompt as text, without the raw audio or
remote URI. Missing voice consent, an unapproved named peer, retained replay,
invalid audio and withdrawal after transcription are checked. Parent IPC,
private speech IPC and the agent terminal remain explicit fixture seams here;
the separate installed-process and speech-authority probes establish their own
boundaries. No live A2A peer or model inference is asserted. This voice probe is
included in the frozen-runtime build and protocol CI with existing reviewed
speech assets; dependencies and model pins are unchanged.
