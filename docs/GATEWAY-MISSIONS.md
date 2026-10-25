# Gateway missions

HAOS connects the **pinned Hermes Telegram, Discord, Slack and Mattermost adapters** to its durable controller for reviewed text paths. Media/voice and live-account acceptance remain open. Historical increments below describe their exact earlier source states.
It uses their actual `register(ctx)`, `PlatformConfig`, `MessageEvent`, `SessionSource`,
`connect` and `send` interfaces, with a HAOS-owned durable dispatch bridge. It never invokes the upstream gateway's
separate agent executor. Only the existing mission worker submits model turns. The image builds
the real adapters and validates their API without connecting to a provider.

## Native dispatch boundary

The pinned generic adapter dispatcher intentionally schedules background agent
work and debounces text. HAOS now inserts a cooperative subclass between each
native transport and that generic base, retaining native transport overrides
(such as Telegram update tracking) while admitting each message synchronously
to the HAOS policy and SQLite spool. It does not alter the pinned source or
monkey-patch upstream classes globally. A failed commit has no accepted receipt;
changed replays fail and duplicates remain one durable record. Automatic plugin
handler/action factories are disabled and the native `HERMES_SAFE_MODE` switch
prevents discovery/import of arbitrary enabled user plugins.

Telegram's native message/inline checks use exact HAOS sender/chat/thread
bindings, without the native env/pairing fallback. Full scope authorization is
still re-applied at spool admission. The legacy native authorization callback
has no workspace field, so it cannot grant another platform's credentialed
context actions on incomplete tenant information. No allow-all switch creates
HAOS authorization.

The required build/provider probe constructs both actual pinned adapters,
verifies the original background/debounce behavior, durable dispatch/reopen,
a real SQLite read-only failure, changed replay, the native Telegram SDK message
and callback gates, and an enabled valid foreign plugin that is not imported.
Both local runtime variants pass **869 tests, two existing skips**. This proves
the native dispatch boundary, not network polling/socket acknowledgement order,
external delivery, media/voice, installed service or the other 20 adapters.
Platform-specific SDK network/reconnect acceptance remains required.

## Owner setup

Use a separately enrolled owner's password-authenticated CLI or trusted recovery console.
Never pass credentials as arguments, chat messages or environment files in a repository.

```sh
sudo haos-owner gateway stop
sudo haos-owner gateway setup telegram-first telegram
# The CLI asks for the bot token with terminal echo disabled.
sudo haos-owner gateway pair my-telegram telegram-first TELEGRAM_USER_ID TELEGRAM_CHAT_ID --identity principal-owner
sudo haos-owner gateway start
sudo haos-owner gateway status
```

For Discord, select `discord`, use stable sender/channel IDs and pass `--scope GUILD_ID` for a
guild. Pair exact threads with `--thread THREAD_ID`. A direct message has empty scope/thread.
One adapter per platform is currently provisioned. Obtain Telegram IDs from an authenticated
transport/admin inspection; display names and message contents confer no authority.

The root-owned policy maps connector + sender + chat + scope + thread to an opaque HAOS
principal and explicit `create/read/cancel/answer/pause/resume` capabilities. Pairing still
defaults to `create/read/cancel/answer`; **existing identities acquire no new capability**.
To enable queue controls, the owner stops the gateway and explicitly pairs using
`--capabilities create read cancel answer pause resume`, then starts it again.
This principal has **no owner
or root privileges**. Credentials are stored root-only mode 0600 and delivered by systemd
credentials to `haos-gateway`. The agent, observer and gateway cannot modify owner policy.
The gateway cannot read backend credentials, mission SQLite, owner files or data mounts. Its
separate Unix socket authenticates the actual kernel peer UID; the usual UI socket cannot
invoke gateway methods. Policy is revalidated for every ingress/delivery request.

Messages create persistent missions. Replies use the same authenticated route. Exact commands:

- `/status MISSION_ID`
- `/cancel MISSION_ID`
- `/pause MISSION_ID` (queued before dispatch only; requires `pause`)
- `/resume MISSION_ID` (paused before dispatch only; requires `resume`)
- `/answer MISSION_ID REQUEST_ID once` or `deny` for an approval
- `/answer MISSION_ID REQUEST_ID clarification text` for a clarification

A principal can control only its own gateway missions, including through another explicitly
paired channel with the same principal. Herald displays these through its existing mission API.
No gateway command changes volume/owner policy or grants permanent tool permission.

## Trusted graphical administration

The local owner setup window can now save exact sender/chat/scope/thread
bindings. Supply the Discord server ID as scope and the actual thread ID when
applicable; an empty scope/thread matches only that empty route, never all
servers or threads. Select each right explicitly. The graphical default remains
`create/read`; existing identities gain no right automatically. Invalid binding
input is rejected before services are stopped.

The same window displays existing binding identities/rights, revokes a selected
binding and removes a connector together with its private credential and dependent
bindings. It uses the same root-protected policy, stopped-service check and owner
audit as CLI administration. Start/stop and a bounded process-status check call
the real fixed systemd unit. A running process is not proof of platform connection
or external delivery. After editing configuration, explicitly start the service.
Provider tokens are masked, cleared after submission and cleared when changing
platform. Configuration/status displays expose no credential values.

Actual Tk fixtures exercise pairing, selected rights, process controls and
revocation at 1280x800 and the scrolling 640x480 layout. A required root CI case
checks real root-owned policy/credential files, a denied alternate UID and
credential removal; local nonroot rendering is not that root/installed proof.
Only Telegram/Discord remain admitted adapters at this increment; the other
20 native integrations, including their media/voice paths, remain open.

## Persistence and revocation

Admission, inbox receipt, route and initial reply commit together. Stable transport message IDs
deduplicate reconnect/reboot deliveries; changed replays fail. Thirty newly admitted messages
per principal per minute is the limit. The outbox persists status, terminal results and question
notifications without exporting arbitrary tool logs. Replies are redacted and durably chunked.
Explicit retryable failures use bounded retries/server delay. An uncertain send or crashed sender
is retained as `uncertain`, because the adapters do not promise idempotent delivery. HAOS never
silently treats it as delivered or blindly repeats it. Model dispatch ambiguity retains the
existing blocked-mission behavior.

Queue pause/resume and their inbox/outbox receipts commit in the same transaction.
Pause survives restart without holding an execution lock. Resume preserves the
deadline/backoff/retry budget and never dispatches directly. Duplicate messages
return the saved receipt, even after that mission executed, without requeuing it.
An expired paused mission fails. Running/waiting/uncertain missions cannot use these
commands. Their safe live resumption remains incomplete.

Stop the gateway before editing pairing/credentials. `gateway revoke BINDING_ID` removes its
authority; `gateway remove CONNECTOR_ID` also removes its credential. Start afterward. Changed
bindings cannot redirect old results. Queued deliveries to revoked routes are marked revoked.
Revocation does not automatically cancel an already admitted mission; cancel it separately.

## Owner recovery of uncertain replies

Stop all runtime services with `sudo haos-owner stop`, then run
`sudo haos-owner gateway deliveries`. This paginated metadata list includes the
delivery ID, actual attempt number, mission ID and content digest; it exports no
message text, recipient or credential. Use `--after CURSOR` to continue.
Inspect the actual authenticated transport separately before deciding:

```sh
# A confirmed existing Telegram/Discord message: no resend.
sudo haos-owner gateway reconcile-delivery DELIVERY_ID --attempt 1 --decision delivered --receipt REMOTE_NUMERIC_MESSAGE_ID --note 'Inspected the transport receipt'
# Retry only if inspection established that the reply was not delivered.
sudo haos-owner gateway reconcile-delivery DELIVERY_ID --attempt 1 --decision retry --confirm-not-delivered --note 'Verified non-delivery in the transport'
# Otherwise permanently revoke this particular delivery.
sudo haos-owner gateway reconcile-delivery DELIVERY_ID --attempt 1 --decision discard --note 'Uncertainty cannot be resolved safely'
sudo haos-owner start
```

Do not put secrets in notes or command arguments. Only the inspection note's
SHA-256 is stored in the mission and owner audit; keep detailed evidence privately.
A hash is trace metadata, not encryption. A retry requires the unchanged authorized
binding, `read` capability, explicit non-delivery confirmation and an unexhausted
five-attempt budget. Attempts are never reset. Stale decisions cannot affect a
later send, pending/delivered/revoked rows cannot be reconciled again, and repair
never changes/requeues the mission. Discard is terminal for that delivery.

The authenticated root CLI verifies stopped services and delegates SQLite work to
the unprivileged `haos-control` UID with no supplemental groups. It never opens the
service-owned ledger as root or sends a transport token to that child. The helper
requires private, correctly owned regular SQLite files, rejects links/missing
ledgers, bounds memory/CPU/runtime/input/output and emits error types without private
payloads. None of these operations is exposed by the UI/gateway sockets. Local
SQLite, validation and actual demoted-UID/canary tests are separate from real provider
delivery evidence; live Codex/Telegram acceptance remains blocked on credentials.

## Evidence and remaining acceptance

The gateway also commits messages in its own private SQLite inbox before the upstream handler
returns. A controller outage or lost admission response therefore retries the same stable key
after reboot. Unadmitted requests expire after 24 hours; revoked bindings are never forwarded.
Transport-side retention/owner UI for expired and denied admissions still needs implementation.

Local ordinary suite: 144 tests. New tests cover replay, identity/room/thread/bot forgery,
foreign-mission control, revoked recipient changes, transactional disk failure, bounded delivery
retry, crash ambiguity and answer admission before an external side effect. A separate real
Unix-socket probe checks kernel peer rejection, gateway methods and persistent admission.
Seven root-authority probes passed in an offline disposable container: actual file modes and
unsafe/symlink/foreign authority-file refusal. No host configuration was changed.
The bundled Telegram/Discord constructors and event/send contracts were run locally using the
80 frozen hash-verified runtime dependencies. They **did not connect or send**.

Real OpenAI Codex credentials and a configured Telegram bot/paired sender are not available.
The full model + authenticated Telegram mission/result round trip remains blocked on those
prerequisites. Installed service operation requires new ISO/guest evidence for this commit.
Attachments, voice transcription, live-job pause/resume, WhatsApp's separate bridge, Slack's scoped
app credentials and other official adapters need additional isolated integration. Unsupported
media is refused explicitly; HAOS does not pretend it was delivered to the agent. Full remote
viewer, credential encryption/retention and owner graphical setup remain separate open gates.

## Pairing generations survive offline revocation (2026-10-24)

Every newly published, re-paired or edited sender grant now receives a fresh
public random generation. An exact unchanged publication preserves its current
generation. Legacy grants acquire one at their next owner publication. Existing
mission and relay records retain their original binding digest, so revocation
followed by identical re-pairing while the controller is offline cannot revive
old replies or relay admissions. Reversing an edit or submitting a stale policy
also creates a new generation. Pairing metadata is not a transport credential.

The additive gateway inbox schema advances to version 2 with the exact original
binding digest per admission. Cached responses cannot bypass a newer grant.
Migration preserves old rows and missions; old admissions whose original grant
cannot be established fail closed on replay, without running the message again.
The owner can still inspect existing missions. Public policy keeps its version-1
format with an optional validated generation field, preserving legacy reads.

Full/minimal local suites pass **972 tests, two existing skips**, including actual
SQLite outage/reopen, repair, edit reversal and legacy migration cases. Actual
pinned Telegram/Discord durable dispatch fixtures also pass without connecting
transports or sending messages. A new mandatory root-file publication case
checks actual owner files in CI; it has not run locally. Source hashes and receipts
are in `docs/evidence/2026-10-24/gateway-generation-validation.json`. This change
does not yet solve crash-atomic credential/account rotation or transport-level
acknowledgement ordering; those remain separate work before adapter expansion.

## Recoverable credential/account replacement (2026-10-24)

Owner publication now journals the approved target and previous policy in a
root-private file, durably withdraws the old policy, replaces credentials and
publishes the matched target. A random publication ID binds public policy to
the exact private credential snapshot delivered by systemd. A mismatched or
pending snapshot refuses adapter startup. Running adapters stop admitting or
sending when the owner publication changes. Writers are serialized by a
root-private lock. Replacing a connector's token/account or platform withdraws
its sender grants, requiring fresh explicit pairing; old account messages cannot
inherit identically named recipients in another account. Mission/history rows
are retained. Exact unchanged grants retain their grant generation.

If publication is interrupted, stop the gateway and use the authenticated owner
CLI `sudo haos-owner gateway recover-configuration`, or the graphical Gateway
page's recovery action. Recovery completes the already approved journaled target;
it does not restore old account authority, fabricate sender approval or send
messages. The journal remains private until completion. Foreign/writable/symlinked
authority paths and malformed snapshots are refused. A token/account change
requires re-pairing before restarting.

Local full/minimal suites pass **979 tests, two existing skips**. Seventeen real
root-file/forked-UID/Unix-socket tests pass in a network-disabled read-only-source
Docker fixture, including fault injection after each fsynced publication stage
and exact-target recovery. This also verifies the preceding pairing-generation
root case. Actual Tk tests invoke the recovery action and render all pages at
1280x800 and 640x480; real Telegram/Discord native dispatch fixtures pass without
connecting. These are not physical power-cut, installed service or external
delivery acceptance. Exact sources, image identity and results are recorded in
`docs/evidence/2026-10-24/gateway-publication-validation.json`. All five CI gates
for provider predecessor `1682f67` passed; new-source CI remains required.

## Telegram offset follows durable native admission (2026-10-24)

Actual PTB polling on the predecessor advanced the Bot API offset while a local
SQLite admission failed. The pinned Updater awaits `update_queue.put` before
confirming its next offset. HAOS now uses that public queue seam to run the real
Application/native handlers serially through their synchronous durable admission
boundary. PTB's shutdown sentinel still uses its ordinary queue. Preparation
errors and held-in-memory events leave the update unconfirmed for actual SDK
retry. Native early handoff markers are deferred until a durable admission or
explicit refusal. A full admission queue raises a retryable failure rather than
being mistaken for a definitive sender refusal. No process-global SDK patch or
replacement Bot client is installed.

The native conflict path also cannot request `drop_pending_updates=True` under
HAOS. A competing consumer can therefore require owner intervention; HAOS does
not discard messages to seize the token. Existing native receipt files remain
untouched; new post-admission receipts use a separate HAOS namespace, including
same-process replacement adapters. Redelivery still passes independent HAOS
identity/grant checks and durable idempotency. Telegram's server retention
limits still apply during prolonged storage/network failure.

Two required build/CI probes use actual PTB Bot API HTTP, the actual native
Telegram application/handlers/codec, and real SQLite. An injected SQLite insert
failure and a native disconnect/hold/reconnect each observe offsets
`0, 0, 13, 13`: the batch retries, and a separate SQLite reader verifies the
commit before confirmation. An unknown sender in the batch is not admitted.
Both probes also pass a native requested drop flag through the HAOS guard and
verify that an earlier legacy receipt neither suppresses admission nor changes
on disk. Explicitly cancelled fixture polls during SDK shutdown are counted;
all other fixture failures remain fatal. Full/minimal suites pass **979 tests,
two existing skips**; existing actual Telegram/Discord constructor and durable
dispatch probes pass too. Exact receipts/sources are in
`docs/evidence/2026-10-24/telegram-polling-validation.json`. All five CI gates for
`1881a20` passed. No external Telegram connection, message delivery, voice/media
or installed-service acceptance is claimed by these local contracts.

## Telegram outbound ambiguity and exact threads (2026-10-24)

The actual native SDK fixture on archived `4fdc7e7` reproduced repeated sends
after the server read the request and disconnected. HAOS now retains the native
adapter's formatting/chunking, per-chat pacing, reply routing and actual SDK,
but sends each chunk once. It never drops the owner-approved thread after a
thread-not-found error. Only an explicit Bot API `BadRequest` formatting refusal
allows the native plain-text codec fallback on the same route. Rich-message
fast paths are excluded until their separate replay semantics are reviewed.

Ambiguous disconnects, HTTP 500 parser errors, malformed/missing/nonpositive
receipt IDs and partial delivery become durable `uncertain` obligations, without
automatic replay. Explicit rate-limit refusals and proven connection/pool failure
before dispatch remain bounded ledger retries. Confirmed forbidden/not-found
refusals are terminal failures. Successful remote IDs are bounded and redacted
before crossing into the controller. The shared decoder no longer treats an
adapter's `retryable` flag alone as proof of non-delivery: other platforms need
their own reviewed certainty markers. Discord's internal send retries remain
a separate next audit, not a completed outbound acceptance.

Ten required actual PTB HTTP/SQLite/reopen cases cover read-disconnect, a server
error containing parser wording, missing thread, rate limit, forbidden, malformed
receipt, invalid numeric ID, confirmed parse fallback, success and an actual
closed local socket before dispatch. All sends stay on the approved chat/thread;
only the confirmed formatting refusal makes a second request. Uncertain rows
remain unsent after reopening; safe retries preserve the durable attempt count.
Fourteen ordinary-user decoder cases cover ambiguous retry flags, partials,
invalid/private IDs and finite/bounded rate timing. Full/minimal suites pass
**993 tests, two existing skips**. Incoming polling/held-reconnect and existing
Telegram/Discord native contracts also pass. Source hashes and complete receipts
are in `docs/evidence/2026-10-24/telegram-delivery-validation.json`. All five CI
gates for `4fdc7e7` passed. No external messages or installed/live Telegram
acceptance are claimed.

## Discord's full native receiving path uses exact HAOS grants (2026-10-24)

The actual native Discord entrypoint on archived `222f6cb` rejected an exactly
HAOS-paired sender because its separate native allowlists were empty. HAOS now
authorizes the complete actual SDK sender/guild/channel/thread tuple before
native preparation and scopes the native user gate to that one receiving call.
Native env, role, pairing and allow-all options cannot authorize another source;
out-of-context native auth remains denied. The final durable inbox independently
checks current owner policy again. Native dedup is consumed only after HAOS
commits, so a failed SQLite write can retry the same actual SDK message.

Native automatic new threads, extra channel-history context, slash-menu handlers
and the separate native response ledger are excluded: they do not own HAOS
authority or its sole reply obligations. Unsupported media is refused before
any native download/transcription. The GUI explains that a Discord thread uses
its own ID for both chat and thread, with the guild ID as scope, and that server
channel messages must directly mention the bot.

Seven required native SDK/SQLite cases cover exact channel admission, other
sender/guild/channel rejection even with native allow-all enabled, failed-write
retry, committed dedup, early media refusal, exact actual SDK thread routing,
and revocation/out-of-context refusal. Full/minimal suites pass **993 tests, two
existing skips**; actual Telegram outgoing/polling and shared adapter contracts
pass. Tk pages also render at both display sizes. Receipts bind exact sources in
`docs/evidence/2026-10-24/discord-native-ingress-validation.json`. All five gates
for `222f6cb` passed. No external Discord connection, WebSocket sequence/heartbeat
durability or complete media/voice acceptance is inferred from these cases.

Inspection of the actual Discord HTTP serializer also confirms that its generated
nonce carries `enforce_nonce=True`. HTTP retries there must be assessed against
that real server idempotency contract; they are not presumed to be the same
unsafe replay reproduced for Telegram. Durable Discord transport capture and
outbound certainty still require separate implementation/proof.

## Discord commits native frames before SDK acknowledgement (2026-10-24)

The private receiving client now captures approved `MESSAGE_CREATE` frames at
the actual SDK's synchronous raw-debug seam, before it updates the resumable
sequence. HAOS commits a bounded, service-private SQLite journal first. A failed
commit closes that socket with its previous sequence; the actual heartbeat
reader cannot acknowledge the uncommitted input. No upstream source is changed.

Live and restarted delivery both decode the redacted stored payload through the
actual Discord SDK and native adapter, check the exact source and current grant
generation, and enter the independently idempotent HAOS relay. A crash after
relay commit but before raw completion cannot create another relay obligation.
Completed payloads are compacted while receipt keys remain; unresolved input is
retained. Pending input expires after 24 hours and decoder retries stop after
eight failures. Storage limits stop acknowledgement rather than dropping rows.

Five actual local WebSocket/SDK/SQLite cases exercise failed commit and heartbeat
sequence, a separate heartbeat thread during insertion, independent-reader
commit visibility, both crash windows, and revoked pending input. This probe is
mandatory in runtime builds and provider CI. Full and minimal suites pass 1000
tests with two existing skips. Exact sources are recorded in
`docs/evidence/2026-10-24/discord-native-transport-validation.json`.

This establishes local durable capture, not external Discord delivery or recovery
of frames after the remote resume window has expired. Long-outage history recovery,
outgoing certainty and complete media/voice paths remain separate work.
No third gateway is claimed.

## Owner recovery of retained native input (2026-10-24)

`haos-owner gateway ingress --after 0` lists up to 100 unresolved receipt metadata
rows, without message text or credentials. `gateway reconcile-ingress ID
--state failed --attempt 8 --decision retry --note 'non-secret inspection evidence'`
reopens a failed decoder budget only while the original 24-hour window and exact
owner grant remain valid. `--decision discard` excludes an unresolved input from
execution while preserving its original payload, envelope and timestamps.
Stale state/attempt decisions are rejected; the decision and note digest commit
atomically in the private journal. Failed audit insertion rolls the decision back.

The authenticated root wrapper requires a stopped gateway and drops to the
`haos-gateway` UID, no supplementary groups and a fixed credential-free environment
before opening SQLite. The graphical gateway page exposes the same real backend,
explicitly stops the service before inspecting it, carries the selected receipt
and evidence into the decision, and leaves restart to the owner. Expired or revoked
input cannot be revived by clicking retry. Recovery makes no provider calls and
sends no external messages. No owner, mission or recovery data is deleted.

Full and minimal suites pass 1008 tests with two existing skips. Nineteen explicit
root/UID/Unix-socket gateway cases include actual demoted-UID retry/discard with a
root-only canary remaining unreadable. The real Tk workflow renders at 1280×800
and 640×480 and exercises the recovery selection/button/backend argument handoff.
Receipts: `docs/evidence/2026-10-24/discord-ingress-recovery-validation.json`.

## Discord outgoing certainty and exact destinations (2026-10-24)

HAOS now scopes the actual native send to the approved guild/channel/thread and
accepts only actual SDK text, thread or direct-message destinations. A forum
parent cannot create a new unapproved thread. The private client's actual HTTP
request must retain the SDK's nonce and `enforce_nonce=True`; its supported HTTP
trace records status/transport outcomes without credential or body logging.
SDK retries retain the same nonce. A later refusal or rate limit following an
ambiguous server/transport outcome or a delivered chunk stays uncertain and is
not automatically replayed by HAOS. Confirmed first-request rate limits and
connector failures before dispatch can retry; confirmed refusal is terminal.

Reply-reference fallback requires a typed SDK HTTP 400/404 refusal. A server
error merely containing a missing-reply code cannot trigger another native send
with a fresh nonce. Actual SDK success must carry a valid positive Discord ID.

Sixteen native-adapter/SDK/HTTP/SQLite-reopen cases cover success, stable-nonce
500 retry, ambiguous-then-forbidden, misleading server reply error, rate limit,
forbidden, confirmed missing reply, malformed/zero receipt, read disconnect,
wrong guild, forbidden forum creation, partial delivery before rate limit,
exact thread success, mismatched thread and refused TCP connection. The same
fixture on archived `0668497` reproduced two sends for the misleading server
error; the corrected path makes one. Full/minimal suites still pass 1008 tests,
two existing skips; 19 real root/UID/socket cases pass. Required probe runs in
runtime builds and provider CI. Receipts bind sources in
`docs/evidence/2026-10-24/discord-native-delivery-validation.json`.

All targets were local fixtures. This does not prove Discord's live remote nonce
deduplication, account permissions or external delivery. Complete media/voice
and long-outage history recovery remain open.

## Discord history recovery after transport outages (2026-10-24)

New or changed owner grants now record an immutable publication-time millisecond
boundary alongside their fresh generation. An unchanged legacy grant retains its
original digest and permissions; without an original boundary it performs no
automatic history fetch. Explicit re-pairing starts a fresh boundary rather than
running old channel messages. The containing millisecond is excluded, preventing
sub-millisecond pre-grant messages from being treated as newly authorized.

The gateway uses the actual installed Discord SDK's authenticated history API,
one bounded page per step, in a separate supervised recovery task. It validates
the actual channel/guild/thread, rechecks the root policy after awaiting HTTP,
and admits only approved messages after the matching grant boundary. Unknown
senders and unsupported content cannot become missions. A cursor advances only
after a durable raw commit or definitive refusal; failed storage/cursor writes
remain recoverable and replay uses the existing raw receipt. Stored history
uses the same actual native decoder and independent HAOS relay as live input.

The original Discord snowflake time is committed atomically with the retained
input. Its 24-hour execution window is not renewed by fetching it later: expired
missed input remains available to the owner but cannot run. Invalid future IDs
cannot advance the cursor. History permission, rate-limit, source, transport and
storage failures persist fixed credential-free status codes; the owner GUI
identifies the grant and explains channel/history permissions. The GUI exposes
the network permissions and explicit re-pairing prerequisite for legacy grants.

Eleven actual SDK/HTTP/SQLite cases cover both commit windows, restart, scope and
grant-time filtering, revocation during HTTP, repaired and legacy grants, original
age/expiry, invalid future IDs, three reversed 100-message pages, and actual SDK
403 reporting to owner recovery. These are mandatory in runtime builds and
provider CI. Full/minimal suites pass 1021 tests with two existing skips; all 19
explicit root/UID/socket gateway cases pass. Tk renders at 1280×800 and 640×480,
including the actual recovery control and permission-status label. Exact sources:
`docs/evidence/2026-10-24/discord-history-validation.json`.

Local fixtures do not establish external Discord permissions or live recovery.
The service needs a correct system clock and the bot's view-channel/read-history
permissions. Already deleted remote messages cannot be recovered. Media/voice
remain refused, and the other twenty gateways remain separate implementation work.

## Slack native ingress contracts in progress (2026-10-24)

The runtime and private policy parser now understand Slack for actual bundled
adapter/SDK contract tests. Owner CLI and graphical provisioning still reject
Slack; it is not yet counted as a third configured GUI transport. Outgoing HTTP
certainty, private two-token owner setup, recovery and GUI integration still need
their own completed evidence before provisioning is enabled.

The private native adapter receives distinct bot and Socket Mode app tokens
through the actual Hermes task-local secret resolver, with a separate provenance
home and no process-environment injection. SDK child tasks inherit only that
scope. Missing profile credentials cannot fall back to another profile's ambient
provider keys. Both gateway credentials enter service-side log redaction.

The exact sender/workspace/channel/thread is checked before native preparation.
Only authenticated workspace clients can capture. The actual SDK Socket Mode
listener commits the bounded private raw journal before invoking Bolt and its
transport ACK. Unknown/unsupported sources receive an explicit transport refusal
without HAOS authority. Actual native message parsing enters the independent
relay; raw claims and policy generations own replay instead of the native
volatile team+timestamp cache. Decoder failure after ACK remains recoverable.

Only message/app-mention Bolt listeners are registered. Native slash/actions,
app-context lifecycle, automatic thread/history hydration, reactions, assistant
status/title writes and media downloads are excluded. Channel and group messages
still require a bot mention; a directly paired 1:1 DM does not. Out-of-context
native user authorization fails closed. SDK HTTP retry handlers are removed and
block-format fallback requires a typed confirmed HTTP 200/400 refusal. Initial
outbound guards require the authenticated workspace and an exact channel/thread;
their full HTTP/outbox validation is still pending.

Nine actual SDK/HTTP/Bolt/local-WebSocket cases cover parallel secret scopes,
independent-reader commit before ACK, duplicate transport envelopes, unknown
sender/channel/workspace, failed raw commit with no ACK, decoder failure after
ACK and reopened replay, exact threads, revocation and late callbacks against a
closed journal. The latter cannot access a closed database or acknowledge fresh
input during service shutdown. Mandatory probe: `probe_slack_ingress.py`.
Receipts: `docs/evidence/2026-10-24/slack-native-ingress-validation.json`.
No live Slack connection or external message delivery is claimed.

## Slack private owner setup and reviewed outgoing delivery (2026-10-24)

Slack now has a real root-owner CLI and graphical setup path with two separate
masked inputs: a single `xoxb-` bot token and `xapp-` Socket Mode app token.
Malformed credentials and token lists are rejected before the GUI stops services.
Both inputs clear on platform changes and submission; private atomic publication
stores both and changing either withdraws existing sender grants until explicitly
re-paired. The desktop catalogue and native setup agree on these three implemented
text gateway paths: Telegram, Discord and Slack. This supersedes the internal-only
provisioning status above and does not claim complete media/voice support.

The setup explains Socket Mode, `connections:write`, bot API scopes, event
subscriptions and channel invitations. Pairing requires exact U/W user, C/G/D
conversation and T workspace IDs, plus an optional full `thread_ts` timestamp.
DMs also require their workspace ID. The original thread is preserved; a flat
reply does not create a new thread, a broadcast or a new DM. Unknown workspaces
cannot fall back to another authenticated client.

The actual SDK client retains its own token/URL/proxy when Bolt copies it. SDK
automatic POST retries stay disabled. The private send context permits only
`chat.postMessage` to the approved channel/thread, with no broadcast. A successful
response needs a valid Slack timestamp and matching channel. Only exact typed
format refusals allow a second send without blocks. A server error or an unknown
error merely mentioning invalid blocks cannot trigger a resend. Confirmed first
rate limits and TCP connector refusal may retry; ambiguity and prior partial
success remain uncertain. Offline owner reconciliation now validates receipt
syntax against the actual current gateway platform, including Slack timestamps.

Eleven actual native SDK/HTTP/Bolt/local-WebSocket ingress cases now include full
native connect, authenticated Socket Mode URL retrieval, actual SDK reconnect and
same-adapter disconnect/reconnect. Independent SQLite readers check the exact
message ID before each transport ACK. Fourteen actual native SDK/HTTP/reopened
outbox cases cover copy identity, success, server/format errors, rate limit,
permission refusal, malformed and wrong-route receipts, disconnect, connector
refusal and exact threads. Both probes are mandatory in builds and provider CI.
Actual Tk tests exercise private input clearing, backend argument handoff and the
640×480 Slack form. Full/minimal Python suites pass 1032 tests with two existing
skips; 26 real root/UID/socket gateway cases include Slack retry/delivered/discard
with the private ledger and root-only canary, plus app-token rotation with actual
durable writes interrupted after each publication stage. Source-bound receipts:
`docs/evidence/2026-10-24/slack-owner-delivery-validation.json`.

No external Slack account, permission grant or message has been tested. Captured
input survives local outages, but Slack messages never delivered beyond its
remote retry window still need a separate history-recovery path. Full media,
voice and additional gateways remain open. No stable distribution is accepted.

## Slack history recovery within exact owner grants (2026-10-24)

The private gateway now also recovers permitted channel/DM history and exact
thread replies through its actual authenticated native SDK client. Each grant
has an independent durable window and provider page cursor. The upper timestamp
stays fixed until every page is processed; a cursor moves only after all approved
inputs in its page are durably retained. A crash or expired provider cursor can
repeat pages without duplicate raw input or missions. Inclusive bounds and a
five-minute overlap avoid a gap at identical timestamps and tolerate delayed
indexing; only the original current grant and its publication boundary authorize
messages. A repaired grant starts fresh; an unchanged legacy grant without a
boundary does no automatic history read.

Requests use at most 15 messages and a conservative minute interval per adapter,
with actual provider Retry-After backoff persisted in the ledger. Fetching old
messages does not renew their original execution age. Unknown users, mismatched
workspace/conversation/thread, malformed pagination, future or out-of-window data
cannot advance history or gain authority. Permission/rate/transport/storage/source
status appears in the same owner recovery UI. Deleted remote messages and absent
history permissions remain real limits, explained in the graphical setup.

Eleven actual local SDK/HTTP/SQLite cases cover descending pages in one fixed
window, both crash windows, reopened actual native decoding, overlap dedup,
expired provider cursors, real rate-limit/permission responses, revocation during
HTTP, repaired/legacy grants, original age/expiry, invalid future data and exact
`conversations.replies` routing. Required build/CI probe:
`probe_slack_history.py`. Full/minimal Python suites pass 1032 tests with two
existing skips; 26 real root/UID/socket gateway cases and both Tk sizes pass.
Receipts: `docs/evidence/2026-10-24/slack-history-validation.json`.
All five CI gates for predecessor `8b4da84` passed. No live Slack delivery,
permission, retention or media/voice acceptance is inferred from local fixtures.

## Graphical outgoing-delivery recovery (2026-10-24)

The trusted local gateway management page now exposes the existing private
outbox recovery actions. Inspection stops all mission and provider services
before reading paginated metadata. An owner can record an inspected platform
message identity, explicitly confirm non-delivery before releasing one bounded
retry, or discard further delivery while retaining the stored data. Existing
platform-specific receipt, current-grant, attempt-budget and private-UID checks
remain authoritative. Notes are hashed by the existing recovery backend.

Services remain stopped after a decision. A separate fixed service-start action
requires completed administrator/recovery setup, a ready normal user, and no
firstboot operation in progress. The same fixed owner action serves the console
and graphical management path. No service name or shell command is supplied by
the UI. Failures propagate to the existing expandable error display.

Both full and minimal Python environments pass 1038 tests with two existing
skips; 26 actual root/UID/socket gateway cases pass unchanged. Native Tk fixtures
exercise the selected receipt and explicit retry confirmation at 1280×800 and
640×480. Service invocation is a local command-contract test, not an installed
systemd or external-delivery acceptance. Source-bound receipt:
`docs/evidence/2026-10-24/gateway-outbox-gui-validation.json`. Fresh GitHub CI
verification was unavailable because the API rejected the configured credentials
with HTTP 401; no successful CI result is inferred for this change.

## Mattermost private transport foundation — not enabled (2026-10-24)

The next adapter now has a private REST boundary exercised through the actual
pinned Mattermost formatter/chunker and aiohttp client. Owner server validation
requires HTTPS, rejects ambiguous paths and embedded credentials, and permits
explicit private-network deployments. Credentials do not travel through redirects.
Reads require a current-authority callback; only a private outgoing context can
create posts. Channel/thread identity and returned receipts must agree exactly.
Native thread-root resolution and notify fallback cannot move a reply into a
different thread or the channel. Media, typing, arbitrary paths and edits are
refused. API bodies are bounded, untrusted provider errors are not logged, and
malformed or wrong-route successful responses retain uncertainty.

Sixteen actual native/HTTP cases cover authenticated read, refused reads/writes,
flat/thread posts, 400/401/403/404/429/500, redirects, wrong-route receipts, native
chunking, malformed and oversized JSON. The probe runs in build and provider CI.
Full/minimal suites pass 1057 tests with two existing skips. Receipts:
`docs/evidence/2026-10-24/mattermost-transport-validation.json`.

Mattermost remains unavailable in the public registry and GUI. This transport
foundation does not establish incoming authorization, durable WebSocket capture,
reconnect/history recovery, owner publication, outbox integration or live delivery.
These remain required before enabling it; the supported gateway count stays three.

Follow-up: private outgoing context is also bound to its exact adapter instance;
a second native adapter cannot borrow it even for the same channel. A later
refusal after a successful native chunk retains partial-delivery uncertainty.
The expanded probe has 18 actual native/HTTP cases, and full/minimal suites
remain 1057 passed with two existing skips. Receipts:
`docs/evidence/2026-10-24/mattermost-route-context-validation.json`.

Fresh CI access was recovered through the connected GitHub tool while local
`gh` credentials remained rejected. All five gates for Slack-history commit
`3af3af908133aef84ce7b0d0926faf7926564bbb` were confirmed successful.
The graphical setup gate also passed for `28042b7` and `741cce1`; other gates
for these later sources were still running at that observation.

## Mattermost owner setup, native ingress and delivery (2026-10-24)

Mattermost now has a real owner CLI and native GUI path. Run `haos-owner gateway
setup mattermost-main mattermost`, enter a separate bot/service-account token
privately and provide the HTTPS server URL (optionally with its deployment
prefix). REST API v4 and WebSocket access are required. The server certificate
must be trusted by the system; there is no TLS bypass or public HAOS webhook.
The bot must belong to the selected channels. Token/server changes use the
existing recoverable private publication and withdraw existing sender grants.

Pair the exact 26-character user/channel/team IDs, optionally the root-post ID.
An empty scope is allowed for actual direct/group conversations; an empty thread
means only messages outside a thread. Mention the bot in channels. Actual server
channel/team metadata and human-user identity are checked under current owner
authority before native preparation; unknown senders, bots, system/edited posts,
media and unsolicited plugin events do not receive execution authority. A native
thread root is verified in its approved channel. Native volatile dedup no longer
owns the commit boundary. Approved originals are captured in the private SQLite
journal before native decoding and durable relay admission; native decoding uses
retained redacted input. Repeated or revoked inputs cannot gain a new mission.

The actual native WebSocket client must receive a successful authentication
response before reporting healthy. Unauthenticated events are ignored; a rejected
challenge is fatal until owner correction/restart. Both HTTP and WebSocket
redirects are refused before credentials can move to another target. Reconnects
reuse durable receipts. Safe last transport status is persisted for the stopped
owner recovery view, including an explicit authentication-refused message. A
stored connected status is historical metadata, not a new live health check.

History recovery pages through actual channel REST history in a fixed descending
window per grant digest. Every approved page input must be retained before the
cursor advances. After a crash, committed raw receipts prevent duplicate work.
If a remote pagination anchor was deleted, the same authorized lower boundary
is restarted and deduplicated. A five-minute inclusive overlap covers equal
millisecond timestamps and delayed indexing. History cannot recover remotely
deleted messages, absent permissions or arbitrary indexing delays. Original
input age is retained: inputs older than 24 hours remain stored and do not run.
Legacy grants without an original time boundary do no automatic history read.
Provider Retry-After and permission/source/storage/transport errors are persisted.

Outgoing native formatting/chunking uses exactly the controller's current owner
binding digest, channel, team and root thread. Each chunk rechecks that digest;
a revoked binding cannot authorize a subsequent chunk. There is no reply-root
substitution or flat-channel fallback. A confirmed refusal may fail or release a
bounded rate-limit retry; a missing response, wrong-route receipt, partial send
or server-side uncertainty stays uncertain. The existing CLI/GUI owner recovery
supports Mattermost receipt IDs without resending on inspection. Removing the
connector removes its private credentials and withdraws its bindings; it does
not delete owner recovery or historical mission data.

Local proof uses the actual pinned Mattermost adapter, aiohttp HTTP/WebSocket
clients, native message codec and real reopened SQLite ledgers: 18 transport,
21 ingress, 17 outgoing delivery and 15 history cases. All four probes are
mandatory in runtime builds and provider CI. Full/minimal Python environments
pass 1058 tests with two existing skips; 35 actual root/UID/socket gateway cases
cover private-ledger recovery and interrupted server rotation. Native Tk verifies
token/URL handoff, clearing, safe status rendering and compact layout. The
Desktop suite passes 841 tests in 115 files. Source-bound receipt:
`docs/evidence/2026-10-24/mattermost-owner-integration-validation.json`.

These are local contract results. No external Mattermost account, installation,
permission, network or real message delivery is accepted. The reviewed text
setup count is four of 22; full media/voice, the remaining adapters, Android,
optional phone firstboot and installed OS/artifact acceptance remain unfinished.


## Prepared Matrix mission admission (2026-10-25)

The private Matrix path now admits actual decrypted SDK events through the
independent HAOS sender/room/root-thread/device policy, retained raw input and
relay, and the actual mission engine. Only the exact decrypted object carries
private crypto evidence; serialized copies and network encryption flags do not.
Owner grants name both device public keys, original grant time and generation,
and explicit plaintext/mention rules. Unknown actors are rejected before SDK
profile/device lookup. Native Hermes still prepares text and source metadata;
HAOS preserves the approved thread and original 24-hour input-age boundary.
Recovery reopens retained input without renewing its authority or timestamp.

Eighteen local contracts exercise actual Olm/Megolm, SDK event decoding, pinned
Hermes text preparation, SQLite raw/relay persistence and real HAOS mission
creation. Twenty-three policy tests cover exact identities, device keys and
revocation. Full and minimal environments pass 1083 tests with two existing
skips; 37 real root/UID/socket checks pass, including rejection of prepared Matrix
publication by the installed owner backend. The other four gateways' thirteen
native regression probes pass. Evidence is source-bound in
`docs/evidence/2026-10-25/matrix-admission-validation.json`.

Matrix remains unavailable in installed setup: the prepared policy is selected
only by private implementation callers, never by root RPC, JSON, CLI or GUI.
The public controller still rejects it. Outgoing delivery, limited-history
recovery, complete profile lifecycle and owner setup remain required before
activation. These fixtures use disposable local identities and create local
fixture missions; they accept no external account, remote trust, inference,
message delivery, installation or release.


## Prepared Matrix outgoing text boundary (2026-10-25)

The next private component preserves pinned Hermes formatting/chunking and actual
Matrix SDK HTTP encoding, while rechecking the exact owner binding/room/thread
before every chunk and at wire authorization. Both the native adapter's broad
E2EE resend and the pinned HTTP transport's independent PUT retry are stopped.
A lost response, malformed receipt, 5xx, redirect or partial multi-chunk send
remains uncertain in the reopened actual HAOS outbox. A confirmed rate limit can
release a bounded retry; inspection never resends an uncertain obligation.
Unsolicited SDK writes outside the private outgoing context remain denied.

Twenty-one actual local SDK/HTTP/native/outbox cases cover exact flat/thread
routes, 400/401/403/404/413/429/500/302, lost connections with exactly one wire
send, malformed receipts, partial sends, revocation between chunks, forged
binding/scope/thread, unsolicited SDK sends and encryption downgrade refusal.
This is a prepared plaintext path only: current room encryption state must be
read successfully or explicitly report absence, and the owner must explicitly
allow plaintext. A stale SDK encryption cache cannot distribute group keys.
Encrypted outgoing messages remain refused until recipient/key-distribution
approval is implemented; inbound device approval is not reused as that proof.
Matrix remains disabled in installed setup. No external delivery is accepted.
Source-bound evidence: `docs/evidence/2026-10-25/matrix-delivery-validation.json`.
