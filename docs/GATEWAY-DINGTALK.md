# DingTalk — private integration in progress

DingTalk is not in the public HAOS gateway registry or owner GUI. Twelve public
software paths are listed in [Gateways](GATEWAYS.md). SDK presence and the private
contracts below are not a complete gateway or live-account acceptance.

The exact pinned upstream `dingtalk` extra contains `dingtalk-stream` 0.24.3 and
`alibabacloud-dingtalk` 2.2.42. Its frozen extras now join the existing nine extras
with one targeted hash-pinned Tea-OpenAPI 0.4.6 compatibility correction.
The frozen 0.4.5 declares Cryptography <49; 0.4.6 permits <51 on Python 3.9+.
HAOS retains Cryptography 50 and MSAL 1.39.0 unchanged. The reviewed upstream
code changes concern throttle-header classification; RSA/HMAC signing and
positive/invalid retry headers have explicit native compatibility contracts.
Preparation rejects an unreviewed extra set. Build/CI run the native codec probe.

Prepared identity requires exact app ID/secret, corporation and robot code. No
caller API URL, plugin setting, alternate auth field or unused token is accepted.
Private policy requires exact native sender and conversation IDs, account scope,
fresh timed grants and separate media/output permissions. Staff/display aliases
and `isAdmin` never grant HAOS rights. The pinned native callback has no topic
route: nonempty topic/thread input is refused instead of widening a chat grant.
Group processing requires the native boolean bot-mention indication by default.

Independent projection validates strict bounded JSON, exact app/robot and both
corporation fields, sender/chat, original timestamp and current grant before
invoking actual SDK models and pinned native pure text/media codecs. Existing
DingTalk recognition text remains voice and requires voice consent; this is not
an assertion of HAOS local ASR. Rich media resolver aliases are canonicalized on
a copy for the actual codec; conflicting codes are refused, original bytes are
unchanged. Video needs video permission even when the pinned codec labels it as
a file. App secrets and private session-reply URLs/capabilities cannot become
agent goals. Incoming resource retrieval and sealed mission dispatch are still
separate pending work.

Private SDK token and connection-discovery operations now have closed scopes.
The actual SDK request builders remain in use. Only fixed API paths and exact
credential/subscription/header shapes are admitted; wildcard events, arbitrary
transport options, redirects, compression and unbounded or malformed responses
are refused. TLS verification stays enabled. Cookie state is cleared rather than
forwarded between SDK requests. Only observed token-cache contents may be reused;
metadata changes or another boundary's cache are refused. Native expiry-buffer
refresh is tested without mocking time. Discovery may produce only a reviewed
DingTalk WSS endpoint and private ticket; the long-running socket is not connected
by this helper. SDK logging is suppressed at its private client, with escaped
credential spellings also registered for redaction. No raw token/ticket is an
owner account-status result. The SDK's unrelated public UDP address probe is
removed from the informational `localIp` hint.

A one-shot account action runs the actual pinned Hermes `_get_access_token`
wrapper and DingTalk SDK under the separate private gateway identity. Parent and
worker check real UID/GID/no supplementary groups and fresh root publication.
The fixed root-owned interpreter, bounded pipes, real CPU/memory/file limits,
30-second worker alarm, parent-death SIGKILL and parent cancellation/revocation
checks constrain that action. Success proves app authentication only: corporation
and robot identity remain unverified, and no message is sent. This helper does
not authorize a sender, install plugins or connect a gateway by itself.

Still required before public activation: supervised native WebSocket lifecycle,
FULL-synchronous original/input custody before the SDK ACK, replay/idempotent
mission dispatch, native replies and media/voice paths, persistent account and
per-write recovery, immediate revocation, source management and complete owner
setup/GUI. The native SDK currently ACKs before its background message handling;
HAOS must connect the independent durable receipt before allowing that ACK.

Local codec, SDK/TLS and private process fixtures have distinct boundaries.
Loopback API substitutions, temporary fixture CA trust, supplied owner policy
and synthetic identities are not live authentication, external delivery,
installed-system or hardware acceptance. No real external messages are sent by
these probes.
