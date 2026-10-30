# Gateways

The pinned Hermes catalog contains 22 adapters. Loading an upstream adapter is
not HAOS integration or authorization. Current public HAOS text setup paths are
Telegram, Discord, Slack, Mattermost, Matrix, ntfy, Home Assistant, IRC, LINE, SMS/Twilio, E-Mail, Feishu/Lark and DingTalk.
Each uses the independent peer-authenticated mission queue, exact owner grants
and its checked transport/delivery path. Unknown senders and plugins receive no
automatic HAOS identity or owner rights. These thirteen software paths are not thirteen
fully accepted platforms or a completed 22-gateway implementation.

LINE additionally connects incoming PNG/JPEG/documents, isolated local voice
transcription and MP4 file attachment, and separately approved outgoing
PNG/JPEG/M4A/MP4/download links. See [LINE owner setup](GATEWAY-LINE.md),
[private media storage](GATEWAY-MEDIA.md) and [local speech](GATEWAY-SPEECH.md)
for exact limits, independent approvals and source-bound tests. Native fixtures
and kernel/UID checks do not establish external recipients, model inference,
public reachability or installed/hardware acceptance.

SMS/Twilio now connects signed text, separately approved incoming MMS and local
voice transcription, outgoing MMS/download links, private API catch-up and
audit-backed recovery. See [SMS owner setup](GATEWAY-SMS.md) for account, TLS,
carrier and acceptance requirements.

E-Mail connects a dedicated IMAP/SMTP TLS account, exact sender/mailbox/thread
grants, retained readonly reception, separately approved MIME files/local voice,
private controller-exported outgoing attachments and inspected UID/SMTP/source
recovery. No-send authentication checks and actual GUI controls are available.
Receiving-server Authentication-Results custody must be independently verified.
SMTP acceptance is not recipient delivery; uncertain writes never auto-repeat.
See [E-Mail owner setup and limits](GATEWAY-EMAIL.md).

Feishu/Lark connects verified native WebSocket or signed/encrypted HTTPS events,
private SDK account/media/reply workers, separately scoped input/output, local
voice conversion and inspected per-part/source recovery. See
[Feishu/Lark setup and evidence](GATEWAY-FEISHU.md) for required app rights, exact
identities, TLS configuration and explicit live-acceptance limits.

The remaining HAOS integrations are a2a, buzz,
google_chat, photon, raft, simplex, teams, wecom and whatsapp. Their bundled
upstream modules alone do not count as working HAOS gateways. Complete each
transport's owner provisioning, sender/chat/thread scopes, durable input/output,
reconnect/replay/recovery, immediate revocation, audit, media and real GUI path
before advancing its status. Existing text paths also retain their documented
platform-specific live/feature acceptance limits.

[Mission and recovery contracts](GATEWAY-MISSIONS.md) remain independent of
transport. No privileged HTTP policy endpoint or text-based root elevation is
provided. Human browser/session credentials are never copied into agent state.

DingTalk connects the pinned Stream SDK with pre-ACK custody, exact app/corporation/robot
identity, explicit sender/chat grants, session or explicitly selected Robot replies,
separate native media/voice/video output and inspected per-part/source/cache recovery.
Its owner GUI provides a no-send app check and one-shot untrusted ID observation
before explicit pairing. See [DingTalk setup and evidence](GATEWAY-DINGTALK.md).
Software/fixture completion does not establish a live account, external delivery,
subscription permissions or installed/hardware acceptance.

The next A2A work remains private/unregistered; see [A2A implementation boundaries](GATEWAY-A2A.md). Its actual native/SQLite/TLS fixtures do not advance the public count.
