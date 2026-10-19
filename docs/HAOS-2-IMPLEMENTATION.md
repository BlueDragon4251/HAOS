# HAOS 2.0 – agreed product contract and evidence gates

Work branch: `agent/haos-foundation`. Do not merge PR #1, main or dev without
explicit approval. Do not mark a capability as working based solely on build success.

## User-approved functionality
- Temporary full administrator desktop on first boot; complete graphical
  configuration; a separate password-authenticated administrator and normal
  account. Never permanently run Hermes or the normal Electron desktop as root.
- Preserve and migrate existing installed user data; no unintended disk wipe.
- Full German and English localization including actual HAOS UI strings.
- System region, keyboard, network, storage, hardware, display, security, backup.
- Automatic bootc updates, private GHCR dev credentials, stable channel, rollback.
- Configure **multiple** providers, multiple models and allowed automatic task
  routing, provider fallback and privacy/cost caps. No terminal command copying.
- Support **all adapters of the pinned Hermes release** with correct individual
  setup, sender authorization and delivery. Upstream adapter existence is not HAOS support.
- Native, polished Android HAOS Mobile app with built-for-mobile Hermes and files,
  responsive real remote desktop and accurate relative mouse/touch/keyboard control,
  QR pairing, explicit scoped rights, device revocation, status, power actions.
- Remote control globally from cellular or other networks without requiring
  Tailscale, a rented VPS, or a second always-on home PC.
- PC wake when hardware/network conditions allow. Otherwise show an accurate
  capability check, not a pretend 'power on' button.

## Network reality
Current Drei ZTE G5TC WAN IPv4 is private 10.174.65.121 (CGNAT). User has
requested a public dynamic IPv4 from Drei; no outcome yet. Until then, there is
**no guaranteed outside-LAN direct connection**. Do not enable router remote admin,
DMZ, UPnP or route unauthenticated VNC to WAN. With a public reachable address,
use dynamic DNS, strict firewall and mutually authenticated encrypted transport.
A completely powered-off PC cannot answer Internet requests. Hardware-supported
WoL requires an external always-on packet origin or a firmware/router wake feature;
do not promise it without evidence.

## Implemented work in this development series
- `apps/mobile`: Android Jetpack Compose shell with device entry, credential
  import and pinned mTLS **read-only** mission listing.
- `haos-mobile.yml`: compiling APK acceptance pipeline; inspect CI conclusion.
- Existing `haos-remote-viewer.service`: owner-scoped, TLS client-certificate,
  read-only mission observer; NOT interactive remote desktop.
- Existing Telegram/Discord HAOS gateway admission, additional Hermes plugin
  catalogue in desktop, **not** active HAOS support for all adapters.

## Must pass before a public 'ready' release
1. Native Android build green and physical phone UI/rotation/gesture verification.
2. Root setup wizard fully end-to-end in real first-boot and migration test.
3. Provider credentials secured from Hermes/normal user and routed by tested policy.
4. Per-platform end-to-end gateway send/receive authorization and retry tests.
5. Mobile cryptographic pairing, replay resistance and revocation tests.
6. Real Wayland screen and input via narrowly-authorized hardware session broker.
7. Mobile-data connection to real HAOS host behind chosen network configuration.
8. Physical HP wake/suspend/power-off and reconnect behavior verified.
9. Stable/dev update + rollback on real bootc image.
10. Locale coverage and German and English strings integration reviewed.

No CI job should upload a production release APK while any mandatory test fails.
