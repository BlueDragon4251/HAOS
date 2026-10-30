# Google Chat — private integration in progress

Google Chat remains outside the public HAOS registry and GUI. The public software
count remains 15/22 after Buzz. The prepared modules below do not constitute a
working installed gateway or live Google Workspace acceptance.

## Implemented private building blocks

A dedicated inline service-account JSON binds the exact project, service email,
expected bot `users/<numeric-id>` and official Google auth/token/certificate
endpoints. Ambient ADC, arbitrary credential paths and token endpoints cannot
be selected by this prepared schema. Pub/Sub mode selects an explicit same-project
pull subscription; HTTPS callback mode requires explicit listener/TLS material,
an exact callback-URL or numeric project-number audience, an unprivileged
listener port and independently expected caller service account.

Independent grants use immutable user, space and optional same-space thread
resources, an account scope and fresh grant epoch. An email/display alias is
never an authorization identity. Mention and incoming file/voice/video/outgoing
file rights remain separate. Google dotted message resource IDs are supported;
path aliases, cross-space resources, pre-grant messages, automated senders and
unknown peers fail before native decoding or attachment work.

The actual pinned Hermes native message builder is exercised for native Chat
and Workspace Add-ons envelopes, group messages and DMs. Its mutable email ID
and DM thread-count heuristic cannot replace the approved sender/thread. The
Google SDK creates the actual service-account RSA assertion with exact bot and
Pub/Sub scopes. This is a local ephemeral-key test, not a real Google token.

The callback-token verifier uses the actual Google SDK for signature, audience,
issuer and time validation, with exact verified caller email checks. Its private
certificate transport has fixed official URL, timeout/body/cache bounds, refuses
redirects and JWK mode (which would create another SDK fetcher), and never
returns or persists a bearer token. Local certificate fixtures are explicit.

FULL SQLite original custody commits before HTTP success or the actual Google
Pub/Sub SDK's ACK queue operation. Replay retains the first original across
semantically identical native/Add-ons envelopes. Changed content/account/grant,
damaged originals and conflicting parent receipts fail closed. Unknown or
malformed Pub/Sub sources need a durable hash-only refusal audit before ACK;
failed original or refusal commits produce NACK. A dedicated real-UID SDK pull transport now uses fixed TLS gRPC authority,
bounded message/RPC sizes and deadlines without SDK retries or emulator/ADC
selection. Its SQL work stays on the owning asyncio thread. Actual SDK client
and local TLS gRPC server checks exercise ACK/NACK, reopen, authentication/
transport failures and publication withdrawal. Real Google service-account
OAuth and the remote subscription remain separate live requirements.

Prepared text writes use the real native `send` formatter and actual Google API
discovery client. FULL write intent precedes the first HTTP byte; stable client
and request IDs bind each operation. Exact threads use `REPLY_MESSAGE_OR_FAIL`,
preventing native fallback into a newly created thread. Per-client HTTP sends
once, bounds responses and does not redirect; actual SDK-generated bearer
values enter the shared private redactor before wire I/O and native error/log
handling; this also prevents httplib2's
otherwise implicit POST resend after a dropped response. A begun/unclear write
can only reconcile with a read of its exact client ID. A 404 is not proof of
non-delivery. Confirmed operations return their retained receipt without HTTP;
changed bodies, routes or revoked grants cannot reuse them. These are private
primitives; controller outbox authority still needs to be connected by the
production profile.

The fixed HTTPS callback application also runs under the actual private UID,
validates trusted TLS material and native Google RSA tokens, retains source or
hash-only refusal before HTTP success, refuses duplicate Authorization headers,
and returns 503 on failed source commits. Its real TLS fixture uses raw TLS
framing for the duplicate-header case because the ordinary test client
normalizes those duplicates before transmission. Publication replacement
prevents subsequent admission. These are receiver-process checks, not a
complete production daemon or remote Google callback acceptance.

The retained original now also feeds the actual native codec and a guarded
cooperative-MRO admission into FULL native and parent-relay queues. A source
ContextVar prevents unretained native events from using that admission. Native
projection hashes, current grant/account and original checksums are checked
again at dispatch. Actual-UID reopen tests keep one parent record, including a
real SQL failure between parent commit and the source receipt. This proves the
local relay handoff, not a root-controller mission or live inference.

## Remaining before public activation

- Complete private profile lifecycle, account identity checks, reconnect and
  scheduling around the implemented authenticated HTTPS and Pub/Sub receivers.
- Durable native dispatch into the independent root mission/controller queue,
  cancellation, outbox authority and inspected owner recovery/status/logout.
- Safe input attachments, local voice and video, sealed controller-exported
  outputs, per-user OAuth setup/refresh/revocation and native upload. The pinned
  adapter requires user OAuth for uploads; service-account auth alone does not
  provide native file delivery. No chat-triggered setup may grant HAOS rights.
- Complete usable owner account/pairing/media/OAuth/recovery GUI, CLI, installed
  packaging, full kernel/UID/process lifecycle and production end-to-end tests.

The optional frozen `google-chat` extra is installed only in the dedicated local
validation environment and dedicated prepared-contract CI workflow. Installed
runtime extras have not been expanded yet. No runtime package versions or
hash-pinned HAOS overlay dependencies were updated.

Source-bound evidence:
[prepared contracts](evidence/2026-10-30/google-chat-private-primitives-validation.json)
and [actual UID receive/relay checks](evidence/2026-10-30/google-chat-private-receive-validation.json).
Loopback HTTP, certificate and SDK ACK-queue fixtures do not establish live
account privileges, subscription authorization, public callbacks, inference,
external recipient delivery/read status, installed OS or release acceptance.
