# Gateways

The pinned Hermes catalog contains 22 adapters. Loading an upstream adapter is
not HAOS integration or authorization. Current public HAOS text setup paths are
Telegram, Discord, Slack, Mattermost, Matrix, ntfy, Home Assistant, IRC, LINE, SMS/Twilio, E-Mail and Feishu/Lark.
Each uses the independent peer-authenticated mission queue, exact owner grants
and its checked transport/delivery path. Unknown senders and plugins receive no
automatic HAOS identity or owner rights. These twelve software paths are not twelve
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

The remaining HAOS integrations are a2a, buzz, dingtalk,
google_chat, photon, raft, simplex, teams, wecom and whatsapp. Their bundled
upstream modules alone do not count as working HAOS gateways. Complete each
transport's owner provisioning, sender/chat/thread scopes, durable input/output,
reconnect/replay/recovery, immediate revocation, audit, media and real GUI path
before advancing its status. Existing text paths also retain their documented
platform-specific live/feature acceptance limits.

[Mission and recovery contracts](GATEWAY-MISSIONS.md) remain independent of
transport. No privileged HTTP policy endpoint or text-based root elevation is
provided. Human browser/session credentials are never copied into agent state.

Private DingTalk SDK/identity contracts are in progress; see
[DingTalk implementation boundaries](GATEWAY-DINGTALK.md). It remains outside the
public registry until transport, durable delivery, media, recovery and owner GUI
are integrated.
