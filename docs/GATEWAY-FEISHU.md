# Feishu / Lark — private integration in progress

Feishu remains outside the public HAOS gateway registry and GUI. Installing the
bundled adapter or SDK is not a working authorized HAOS gateway. Eleven other
public paths are listed in [Gateways](GATEWAYS.md).

The frozen runtime now includes the pinned upstream `feishu` extra: actual
Lark OpenAPI 1.6.8 and requests-toolbelt 1.0.0. The existing eight extras and
hash-pinned overlay, including MSAL 1.39.0, remain unchanged. Preparation checks
the exact upstream source hashes and refuses an unreviewed extra set. The
native SDK probe uses real Hermes builders, real Lark models and actual
loopback HTTP for tenant-token acquisition, bot lookup, authentication failure
and rate limits. It does not contact a real Feishu/Lark app or send a message.

Prepared private identity validation requires an exact app ID/secret, explicit
Feishu or Lark brand, tenant key and bot open ID. No arbitrary API URL, plugin
settings, display-name or alternative user-ID authorization is accepted. Sender
open IDs, chat IDs, optional native topic IDs and fresh timed owner grants are
separate. Account scope binds brand/app/tenant/bot. Media permissions default
to denied and require appropriate mission rights. Websocket mode accepts no
unused webhook secrets; webhook mode requires verification token, encryption
key and reviewed HTTPS listener material for `/feishu/webhook`.

Actual Lark event decoding retains millisecond timestamps as strings and
keeps `thread_id` distinct from the quoted `root_id`. Its SDK token cache uses
app-ID keys; private profile/credential/brand isolation must be enforced when
transport is connected. Native send retries and reply fallbacks also need
independent durable HAOS limits. HAOS will not delegate owner identity to the
upstream allow-all or pairing defaults.

Transport/listener authentication, persistent ingress, bounded single-write
replies, replay/recovery, media/voice and owner GUI integration are still open.
Local SDK and identity tests do not establish live-account, external delivery,
installed OS or hardware acceptance.


Independent input projection now checks bounded duplicate-free finite JSON,
application and both tenant fields, exact open sender/chat/native topic, user
role, own-bot exclusion and both original millisecond time boundaries before
calling the native codec. Group mentions require exact bot open-ID metadata;
quoted roots, display names, user-ID aliases and @all do not grant access.
This function consumes already authenticated bytes; it does not authenticate
webhooks or sockets by itself.

The actual Lark model and pinned Hermes normalizer produce text, rich posts,
mention/command handling and resource descriptors without a client, download or
local file write. Header/body snapshots and current grant hashes are checked
again; private credential reflection is refused. Image/document, audio and video
permissions remain separate even when the native SDK labels a video resource as
`file`. Rich-post tags and duplicate resource keys require all corresponding
owner approvals. The real SDK fixture reproduced and caught the initial video
consent mismatch; fixed fixtures retain their negative assertions.

This is still a private codec/admission stage. Authenticated transport, durable
capture/dispatch, actual resources/voice, replies and owner GUI remain unfinished.
