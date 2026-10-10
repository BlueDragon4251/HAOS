# Source-bound acceptance receipts

`index.json` ties these unchanged receipts to exact implementation, CI merge,
archive and installed-image identities. File SHA-256 values refer to the adjacent
JSON bytes. Archive digests refer to the original GitHub ZIP bytes; the ISO digest
refers to `haos-x86_64-development.iso`, separately verified by the installation job.

- `guest-0a-boot-1.json` and `guest-0a-boot-2.json` came from original guest artifact
  `11670798449` in [installed run 38049123871](https://github.com/BlueDragon4251/HAOS/actions/runs/38049123871).
  Both saved receipts were matched against the actual serial logs. Post-reboot
  owner/recovery assertions are intentionally false at boot 1 and true at boot 2.
- `wayland-ci-2aacca.json` and `theme-ci-2aacca.json` came from original artifact
  `11670098815` in [CI 38054327172](https://github.com/BlueDragon4251/HAOS/actions/runs/38054327172).
  Source `2aacca8` is the tested PR merge of baseline `3c891ad` and branch `82e6ca5`.
- `wayland-local-82e6.json` came from a clean local `82e6ca5` checkout in a disposable,
  offline, unprivileged Ubuntu 24.04/Weston 13 desktop-shell container. The container
  had actual compositor helpers/assets and Chromium dependencies. Renderer sandbox
  flags were independently checked; neither host provisioning nor real model use
  was performed.

Only disposable assertion/identity JSON is retained here. Profiles, protocol logs,
databases, screenshots, credentials and private chat bodies are excluded. The real
Wayland theme fixture exercises production engine, preview, renderer and independent
watchdog; it is a representative component fixture, not the installed niri/Herald
session. The installed receipts prove ledger backup/restore while runtime PIDs are
preserved, not arbitrary live filesystem consistency or a provider-backed mission.

Real model/gateway turns, general host applications, remote streaming, autonomous
theme/skill generation, complete system recovery, signing and physical hardware
remain open. These receipts do not authorize a stable release.

`supplement.json` records later installed successes at `82e6ca5` and `fd7987d`,
and the successful repeat of the original `327f3cd` image/guest protocol with the
corrected `fd7987d` harness. The retry's unchanged `test-source.json` is retained
separately: image, guest, harness and diagnostics remain distinct identities.
The three matching boot-1 receipt byte sequences are identical to the original
`guest-0a-boot-1.json`; supplemental second-boot receipts remain source-bound by
archive and file digests. The newer theme parent-SIGKILL/recovery assertions are
explicitly marked unaccepted until their own installed run supplies real receipts.
