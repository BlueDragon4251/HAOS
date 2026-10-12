# Authenticated mission observation

HAOS has a separate, **disabled by default**, read-only HTTPS viewer. The owner
configures a TLS server identity and client CA through the password-authenticated
`haos-owner remote` CLI. TLS 1.3 and a valid client certificate are mandatory.
Each certificate must also have an explicit owner-paired fingerprint, expiry and
list of mission UUIDs. Trusting the CA alone grants no access. Pairing lasts 1–24
hours; revocation/expiry and scope are checked for every request in both the viewer
and controller, including an already established TLS connection.

```sh
sudo haos-owner remote configure --server-cert /ROOT-PROTECTED/server.pem \
  --server-key /ROOT-PRIVATE/server-key.pem --client-ca /ROOT-PROTECTED/clients-ca.pem
sudo haos-owner remote pair phone /ROOT-PROTECTED/phone.pem --mission MISSION-UUID \
  --hours 1 --share-content --share-screenshots
sudo haos-owner remote start
sudo haos-owner remote revoke phone
sudo haos-owner remote stop
```

These paths refer to actual owner-provisioned PEM files, not repository fixtures.
Private keys must be root-owned, private, regular and unlinked; the owner copies
them into a private configuration directory and systemd delivers them only to
`haos-viewer` with `LoadCredential`. No key appears in argv, URLs, HTML, audit or
the agent namespace. The service has no capabilities, login, owner or general
controller rights. The device private key stays on its device. The owner provisions
the device certificate and trusted server CA through a protected device channel;
automatic QR enrollment, graphical setup and identity rotation are still open.

The default listener is `127.0.0.1:8443`. An owner may explicitly select a literal
bind address and unprivileged port during configuration. The certificate must
cover the address/name actually used by the browser; certificate verification is
never disabled. There is no default internet port, VNC/RDP server or port-forwarding
rule. The user opens HTTPS with the paired device certificate and trusted server
CA. No bearer token is placed in the address or stored by browser JavaScript.

The responsive page shows **real persisted mission state/events** and the last
real private application capture, when explicitly shared. Content and screenshots
are separate opt-ins; otherwise only bounded mission/event metadata is shared.
Frames expire after 15 seconds and are removed after errors or mission cancellation.
This is polling of recent actual captures, **not continuous video or whole-desktop
capture**. Remote input, mission creation/cancel/pause/answers and owner operations
are not exposed by this read-only scope. Browser/scripted application support,
terminal completeness and full authenticated remote workflows remain open.

The viewer uses its own Unix observation socket, with both kernel peer UIDs checked.
It cannot consume native GUI actions or access the unrestricted bridge. The controller
reloads root-owned scope before every read, filters missions, and records bounded
attributable observation events without copying content or pixels into access audit.
Request/response size, TLS/HTTP time, connections, requests per minute and actual
response bytes per minute are bounded. Replies use no-store, strict CSP and no CORS;
mutations, duplicate headers, body requests and cross-origin requests are rejected.

`test_remote.py` makes real TLS 1.3 connections with freshly generated disposable
CA/server/client certificates to the actual viewer, kernel Unix socket and persistent
MissionStore. It checks reconnect, scope, missing/unpaired certificates, expiry,
revocation, rate limits, content consent and denied operations. No provider responses
or fake screen frames are involved. This local integration has one fixture UID;
separate installed service UIDs, real browser/device rendering and real application
capture delivery need their own gates. Existing application captures are produced
by the separate real Wayland/systemd pipeline. No installed remote acceptance or
complete privacy/release approval is claimed by a local TLS test.
