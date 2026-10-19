# Gateway missions

HAOS now connects the **pinned Hermes Telegram and Discord adapters** to its durable controller.
It uses their actual `register(ctx)`, `PlatformConfig`, `MessageEvent`, `SessionSource`,
`set_message_handler`, `connect` and `send` interfaces. It never invokes the upstream gateway's
separate agent executor. Only the existing mission worker submits model turns. The image builds
the real adapters and validates their API without connecting to a provider.

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
