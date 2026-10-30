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
