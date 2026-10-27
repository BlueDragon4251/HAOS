# LINE owner setup — text integration, not complete platform acceptance

HAOS now exposes the prepared pinned Hermes LINE text path through actual owner
CLI and graphical setup. This replaces the earlier **publicly disabled** state.
It does **not** complete LINE media/voice support, external account/recipient
acceptance or installed OS acceptance. Nine platforms now have public text setup
paths; that count is not nine complete gateway acceptances.

## Configure the real listener

1. Enable the Messaging API and webhook in the LINE Developers Console. Obtain
   the exact channel secret, channel access token and bot destination (`U` plus
   32 lowercase hexadecimal digits). Use a separate bot identity. Native bot-info
   lookup must confirm that destination before listening or sending.
2. Prepare a public DNS name and current system-trusted server certificate chain
   with the matching unencrypted private PEM key. The URL is exactly
   `https://hostname/line/webhook`, publicly on port 443. Public IP URLs,
   credentials/query strings in URLs, other paths and nonstandard public ports
   are refused. PEM input files must be regular, single-link, owner/root-owned,
   private (`0600`) and bounded (chain 16 KiB, key 8 KiB). The graphical importer
   requires the trusted local owner seat and displays no PEM bytes.
3. In owner management select **line**, enter destination, local HTTPS port
   (1024–65535), public URL and bind address. Load certificate and key separately,
   then enter the masked channel secret and token. A public bind (`0.0.0.0` or
   `::`) needs separate explicit consent. Loopback (`127.0.0.1`) is the default.
   CLI: `haos-owner gateway setup line-main line`; it uses protected secret
   prompts and private PEM file reads, with `PUBLIC` confirmation for public bind.
4. Configure the **host firewall** to permit the chosen local HTTPS listener port
   when public bind is intended. The shipped firewalld zone otherwise denies
   unsolicited ingress. Configure the router/TCP proxy to forward public port
   443 to that TLS listener, or a local TCP proxy for loopback mode. HAOS does not
   silently modify firewall rules, router settings, public DNS or certificates.
   Public binding alone proves none of these external prerequisites. CGNAT needs
   an independently reachable relay/tunnel/public address; no direct reachability
   through CGNAT is claimed. Do not forward plaintext into this HTTPS listener.
5. Pair each authorized sender before starting. Without a matching timed owner
   grant the connector remains inactive. For example:

   ```text
   haos-owner gateway pair owner-line line-main U<32 hex digits> C<32 hex digits> --identity personal --capabilities create read cancel answer pause resume
   ```

   Use the sender's exact `U…` ID; a direct chat must equal that sender ID.
   Groups use `C…`, rooms `R…`. The bot destination scope is derived from saved
   private credentials and checked against any supplied `--scope`. Bot self-
   authorization, other destinations and nonempty threads are refused. Group/
   room replies are visible to all members; only explicitly paired sender IDs
   gain mission rights. Display names and unknown senders never gain authority.
6. Start with the existing gateway service controls. Enable the exact webhook
   URL and redelivery on the LINE side. Perform the account/network verification
   yourself before relying on remote missions; local fixtures are not that check.

## Recovery and renewal

Signed requests reach committed private native input before HTTP success. Native
decode feeds the durable relay/mission engine; stored failures survive restart.
The outbound native push path journals intent before HTTP and keeps provider
acceptance separate from recipient delivery. An interrupted/uncertain send is
not automatically resent. Use owner input/output inspection and explicit audited
delivery decisions. A LINE receipt has the form `line_push_<64 hex digits>` and
does not prove that a recipient read or received the message.

After correcting channel login/destination errors, the graphical recheck or
`haos-owner gateway retry-line-auth line-main --note 'account corrected'` records
an offline owner decision. It preserves throttle deadlines, revocation and
retained inputs; restart must still pass actual native account verification.

Native outbound HTTP 401/403 also pauses the connector and persists an account
authentication block; 429 pauses it until the private stored Retry-After deadline.
Other unsent obligations retain attempt zero while the connector is not ready.
Sends, reconnect and close are serialized so another request cannot escape while
the listener is being stopped. These blocks survive profile reopen. An owner
authentication recheck cannot shorten a rate deadline; after correction/expiry,
fresh native bot verification precedes sending previously unsent replies. See
`line-outbound-block-validation.json` for the reproduced prior 401 defect and
actual HTTP/mission-outbox/reopen recovery cases.

Replacing credentials, listener settings or certificate material withdraws old
sender grants. Re-pair explicitly and restart; old events cannot inherit a new
grant epoch. Secret/PEM inputs clear after submission and context changes. A late
file-import result is discarded if its configuration context changed.

Expired certificates remain inspectable and replaceable in owner configuration.
They cannot activate a listener: trust, hostname, key and time are checked before
any connection attempt. Refusal persists as a safe TLS diagnostic through close/
disconnect rather than crashing all connector construction. Configure current
material, re-pair and restart. Existing private files with conflicting contents
are preserved and require owner recovery. Remove/revoke leaves retained owner
and recovery data intact; externally managed firewall/proxy rules remain the
owner's responsibility and should be withdrawn when retiring the listener.

## Evidence and remaining work

Source-hashed evidence is in
`docs/evidence/2026-10-27/line-owner-setup-validation.json`. Native fixtures run
actual pinned parsers, HMAC, bot-info/push clients, HTTPS, private SQLite journals
and mission/outbox code against loopback endpoints. A separate disposable root
run exercises real private PEM files, CLI publication/pairing, credential and
certificate changes, foreign UID denial, remove and audit. Its service-stopped
inspection and audit-directory relocation are fixtures, not installed systemd
or owner-seat acceptance. Tk cases use real controls with explicit backend
handoffs. Both full and minimal Python suites and the independent kernel/UID
regressions remain required; GitHub CI must be attributed to its exact SHA.

The additional `line-actual-uid-sigkill-validation.json` receipt covers four
actual process cases. Public HAOS code, the pinned native adapter and frozen SDK
are installed root-owned/read-only in a fresh disposable container. UID 65534
passes the production runtime identity guard, handles a signed HTTPS webhook and
commits its private relay, then performs a native verified-HTTPS push. A real
SIGKILL interrupts that request after the durable write intent. UID 65533 cannot
read/open the journals or owner canary. A new gateway process reacquires the
kernel lease, preserves the committed input, marks the old write uncertain and
does not repeat the push. CA registration and endpoint substitution are confined
to this network-isolated fixture; this is not an installed HAOS/systemd, public
network, LINE account or recipient test. Both provider CI runs require it.

**Still open:** binary files/images, voice and other media require a reviewed
shared media broker through missions and the agent. They are not enabled by this
text setup. This integration does not claim all 22 gateways, real LINE accounts,
external message delivery, installed boot, hardware tests or final ISO/container/
APK release acceptance. No external test messages are sent by these fixtures.
