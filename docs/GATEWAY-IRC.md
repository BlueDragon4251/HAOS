# IRC gateway software acceptance

HAOS implements the owner-authorized IRCv3 **channel gateway** using the pinned
Hermes IRC adapter. Its supported transport is authenticated TLS, exact server
and channel, server-authenticated sender accounts and explicit per-sender mission
rights. The implementation includes owner CLI and actual graphical setup,
private credentials, mission ingress/replies, reconnect, persistent replay and
outbox recovery, revocation, audit and operator diagnostics.

This document does not claim external account, recipient or installed-machine
acceptance. Those results must be recorded separately. The source-linked local
receipt is `docs/evidence/2026-10-26/irc-software-completion-validation.json`.
Required GitHub checks for the exact implementation commit must also pass before
treating the software acceptance as complete.

## Covered implementation

| Requirement | Implementation and verification |
| --- | --- |
| Setup and private login | Actual CLI and Tk fields for TLS hostname/port, bot nickname, channel, optional server PASS and channel `+k` key, and SASL account/password. Anonymous bot connection needs explicit owner approval. Private fields clear after submission/context changes. Native SASL PLAIN runs only over verified TLS, with correct chunking and account confirmation. |
| Independent authorization | Exact authenticated sender account, server/port, channel, identity and selected create/read/cancel/answer/pause/resume rights. Nicknames never authorize a sender. Unknown accounts/plugins, different endpoints/channels, expired grants and stale grant epochs cannot inherit authority. No connection before pairing. |
| Incoming missions | Actual pinned native parser/codec behind committed private NativeInbox and RelayInbox, then the mission engine. Stable server message IDs and original time bind replay protection and timed owner grants. Channel messages must address the bot. Common mission command contracts enforce identity ownership and selected permissions. |
| Replies | Actual pinned markdown/UTF-8 chunker and sender behind current owner checks and an intent saved before socket writes. Each chunk requires correlated label/echo/batch proof. One uncertain attempt cannot resend; confirmed attempts reuse their durable receipt. Replies are visible to channel members. |
| Recovery | Durable inbox/outbox and profile reopen, kernel lease release, actual process SIGKILL/restart, disconnect/reconnect, stored rate deadlines, sticky authentication refusal and explicit audited owner recheck. Uncertain sends require inspected retry/delivered/discard decisions; retries require confirmed non-delivery. Recovery preserves retained input and owner data. |
| Status and errors | Real service controls, private ingress/output inspection and GUI. Bounded persisted diagnostic codes distinguish TLS/DNS/connection faults, missing capabilities, occupied nickname, invite/key/ban/full/not-found channel cases and refused forwarding. Vendor bodies and credentials are not used as operator messages. Legacy diagnostic-less journals remain readable. |
| Revocation/removal | Root-only atomic matched policy/credential publication. Credential/key changes withdraw old sender grants; re-pairing gets a fresh epoch. Revocation blocks new input/output and closes the old connection. CLI remove clears configured credentials and grants while preserving owner/recovery data. Previously admitted missions remain subject to their own mission controls. |
| Service/credential boundaries | Real/effective/saved UID/GID checked before runtime credential loading, no unexpected supplementary authority, private HOME/journals/locks, systemd credential delivery and immutable pinned code. Real UID/NSS/file/socket/recovery tests are separate from GUI backend-handoff fixtures. |

## Protocol and security boundaries

The server must provide `account-tag`, `server-time`, `message-tags` and stable
`msgid` values; replying additionally requires `echo-message`, `labeled-response`
and `batch`. TLS certificates must validate for the saved hostname against the
system trust store. Unsafe plaintext/verification bypasses and nickname-based
sender authorization are not setup options. NickServ password forwarding is not
used; SASL is the reviewed account login path.

The configured scope is one exact channel per isolated IRC connector, with
multiple explicitly approved sender accounts. Use an appropriately managed
private/invite/key-protected channel when replies should not be public.
Unapproved direct-message routes and channel forwarding are refused. These
restrictions are enforced owner/security boundaries, not inferred permissions.

The pinned IRC adapter has no native binary document, audio/voice or video
transfer. HAOS supports text and HTTPS links and explicitly refuses unsupported
binary transfer methods before any fallback upload or misleading success. It
does not implement DCC or expose private host paths. This is the IRC protocol
scope; other platforms still require their own media broker integration.

An IRCv3 server may synthesize an echo when filtering a message. A correlated
server echo therefore proves only the recorded server acceptance contract, never
receipt by every channel member. The GUI and receipts state this explicitly.
Unobserved messages during an outage cannot reliably be fetched from stock IRC
history; reconnect does not close or erase the recorded history gap.

## Owner operation

1. In graphical owner management select `irc`, enter and save the real TLS/login
   parameters. The optional channel key supports `+k` channels. CLI equivalent:
   `haos-owner gateway setup irc-main irc`; secrets use private prompts.
2. Pair the actual registered sender account with its channel and intended
   HAOS identity/rights. For example:
   `haos-owner gateway pair owner-irc irc-main OwnerAccount '#private' --identity personal --capabilities create read cancel answer pause resume`.
   The saved server/port scope is derived and checked; unsaved endpoints do not
   gain authority. Server account case must match the observed account tag.
3. Start the gateway service and inspect status. Send an addressed mission from
   the approved account. `/status`, `/cancel`, `/answer`, `/pause` and `/resume`
   operate only on missions of the approved HAOS identity and corresponding right.
4. After an account correction, use the GUI recheck or
   `haos-owner gateway retry-irc-auth irc-main --note 'account corrected'`, then
   restart. This is an offline owner decision; it never bypasses server login,
   a future throttle deadline or revocation.
5. Inspect stored inputs/outbox before deciding an uncertain delivery. Use the
   existing GUI actions or `gateway ingress`, `gateway deliveries`,
   `gateway reconcile-ingress` and `gateway reconcile-delivery --help` for exact
   attempt/state/evidence arguments. Do not retry an outcome merely because no
   local success was observed.
6. Revoke individual sender bindings or remove the connector through owner
   management/CLI. Re-pair after credential changes. General boot, desktop and
   release acceptance is tracked separately in Issue #2.

## Evidence boundaries

The native probes execute the real pinned codec, TLS streams, SASL, native sender,
private SQLite journals and mission/outbox code against disposable local servers.
The process probe runs installed public pinned code under actual gateway/agent
UIDs and uses a real SIGKILL. Root CLI publication/rotation/removal and recovery
use real private files and UIDs; the CLI lifecycle fixture supplies the
service-stopped inspection and relocates the audit directory. Tk fixtures exercise
real controls with explicit backend handoffs. They are not a claim of an installed
owner seat or external delivery.

Only an owner-operated real IRC server/account check can establish the remaining
live network/certificate/account/recipient acceptance. No external messages are
sent by the fixture suite. This gateway acceptance does not release an ISO,
container or APK and does not complete the other HAOS project requirements.
