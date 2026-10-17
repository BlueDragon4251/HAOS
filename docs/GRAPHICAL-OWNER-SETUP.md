# HAOS graphical administrator first boot — development acceptance

**Experimental on `agent/haos-foundation`.** The current development image now
**enables** a dedicated graphical setup service. On a fresh HAOS install,
`haos-setup-gate` suppresses the normal greetd desktop until a separate
owner, recovery codes and the normal observer profile have completed setup.
An already enrolled owner with recovery and no interrupted wizard **skips** the
new privileged setup screen (migration; existing files and users are kept).
The decision runs as root, not through an agent or remotely supplied message.

There is **no complete installed UEFI/BIOS VM or physical HP acceptance yet**.
The native window passed Xvfb seven-screen rendering at normal and 640×480
resolutions, syntax and permissions unit tests. A successful test or container
build does not prove real graphics, Wi-Fi, input or completed reboot on hardware.
Do not release this branch as production-ready on the basis of those tests.

## Implemented pieces

- Private root-owned Xorg display `:8` on VT8, non-TCP, random protected
  Xauthority cookie, explicit Austrian keyboard before password entry,
  physical VT activation, no privileged Electron/Hermes browser.
- Seven responsive, vertically scrollable graphical pages:
  administrator and recovery, normal user, language and keyboard, Hermes
  provider/model, stable/dev image updates with private GHCR credentials,
  Telegram/Discord bot credentials and sender bindings, and finish/reboot.
- Separate 20+-character owner password validation through HAOS enrollment;
  ten one-time offline recovery codes must be displayed and acknowledged.
  Interrupted attempts and pre-existing owner accounts missing recovery can
  continue in the physical wizard without wiping an account or personal data.
- A **durable wizard-in-progress marker** prevents a crash after saving recovery
  codes from opening the normal desktop before the wizard has finished.
- Observer name and per-user locale/keymap are transferred through a bounded
  fixed-account writer; no arbitrary paths/usernames, secret-bearing command
  lines or untrusted symlinks. Existing session setup receipts are preserved.
- Owned gateway/provider changes stop and check relevant services before
  changing live secrets, without asking the operator to paste commands.
- Protected owner-only stable/dev bootc and GHCR credentials reuse the
  existing root authority implementation. The prior bootc deployment remains
  subject to tested rollback behavior.

## Important current limitations

- **Root window/VT8 real boot must still be tested.** If it fails, the
  independent physical tty2 recovery console remains the supported fallback.
  No automatic fail-open root shell or unrestricted desktop is provided.
- The normal desktop remains the existing locked non-administrator observer
  Unix account, with a user-chosen **display name**, not a new full interactive
  Linux login account. Distinct personal interactive Unix accounts still need
  integration work.
- Provider GUI configures **one active provider**. The separate pure automatic
  multi-model routing policy is not wired into the live Hermes broker; multiple
  simultaneous providers and per-task model choice are not delivered yet.
- Only Telegram and Discord have HAOS gateway authorization. The wider Hermes
  plugin catalogue is not equivalent to HAOS runtime support.
- Mobile is an Android APK with read-only owner-granted mission inspection;
  actual remote desktop capture, low-latency touch, secure QR pairing, revocation,
  worldwide connectivity and remote wake remain to implement and physically test.
- Current Zwei-route firstboot language choices include `de_AT.UTF-8`,
  `de_DE.UTF-8`, English and French, but **full interface translations** have
  not been completed.
- Public reachable Drei WAN connectivity is **still pending**. Do not enable
  router DMZ, UPnP or unauthenticated WAN admin.

## Required acceptance before stable or a real daily-driver update

1. Actual Fedora 44 image and ISO build, installation and reboot into VT8 on
   disposable UEFI and BIOS QEMU, with video/keyboard/mouse interaction.
2. Physical keyboard mapping, mouse, UI scaling and root-secret isolation on HP.
3. New owner account and offline recovery codes fully exercised with PAM/sudo,
   crash-and-retry at every enrollment stage, then normal user login on reboot.
4. Already enrolled installation migration and user-file preservation.
5. End-to-end firstboot stable/dev updates, live provider tokens and model
   calls, gateway delivery and revocation.
6. Full translations, integration of multiple models/providers and gateway
   platforms, then Android paired streaming/input/wake acceptance.

`haos-recovery.service` on tty2 is not removed. Avoid a production release or
an unattended upgrade of the daily-driver HP until actual boot acceptance.
