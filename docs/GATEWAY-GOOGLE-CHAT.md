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
an exact audience and independently expected caller service account.

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
failed original or refusal commits produce NACK. Actual remote SubscriberClient
authentication and server ACK acceptance remain unimplemented/unverified here.

Prepared text writes use the real native `send` formatter and actual Google API
discovery client. FULL write intent precedes the first HTTP byte; stable client
and request IDs bind each operation. Exact threads use `REPLY_MESSAGE_OR_FAIL`,
preventing native fallback into a newly created thread. Per-client HTTP sends
once, bounds responses and does not redirect; this also prevents httplib2's
otherwise implicit POST resend after a dropped response. A begun/unclear write
can only reconcile with a read of its exact client ID. A 404 is not proof of
non-delivery. Confirmed operations return their retained receipt without HTTP;
changed bodies, routes or revoked grants cannot reuse them. These are private
primitives; controller outbox authority still needs to be connected by the
production profile.

## Remaining before public activation

- Actual private service identity, profile lifecycle, authenticated HTTPS
  listener and isolated Pub/Sub subscriber, reconnect and scheduling.
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
[prepared contracts](evidence/2026-10-30/google-chat-private-primitives-validation.json).
Loopback HTTP, certificate and SDK ACK-queue fixtures do not establish live
account privileges, subscription authorization, public callbacks, inference,
external recipient delivery/read status, installed OS or release acceptance.
