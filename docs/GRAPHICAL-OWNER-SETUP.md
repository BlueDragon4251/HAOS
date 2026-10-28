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

- Private root-owned Xorg display `:8` on VT1 (F1), non-TCP, random protected
  Xauthority cookie, explicit Austrian keyboard before password entry,
  physical VT activation, no privileged Electron/Hermes browser.
- Seven responsive, vertically scrollable graphical pages:
  administrator and recovery, normal user, language and keyboard, Hermes
  provider/model, stable/dev image updates with private GHCR credentials,
  Telegram/Discord bot credentials, separate Slack bot/Socket Mode app tokens,
  private Mattermost tokens with an explicitly validated HTTPS server,
  and Matrix access tokens with exact homeserver/user/device and sender-key approval,
  exact sender/workspace/thread bindings, and finish/reboot.
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

- **Root window/VT1 real boot must still be tested.** If it fails, the
  independent physical tty2 recovery console remains the supported fallback.
  No automatic fail-open root shell or unrestricted desktop is provided.
- The normal desktop remains the existing locked non-administrator observer
  Unix account, with a user-chosen **display name**, not a new full interactive
  Linux login account. Distinct personal interactive Unix accounts still need
  integration work.
- Provider GUI manages multiple private profiles, discovered/approved models, a
  default and explicitly approved fallback routes. Provider/account-specific live
  acceptance and remaining protocol limitations are documented in PROVIDER-PARITY.md.
- Telegram, Discord, Slack, Mattermost and Matrix have reviewed HAOS text gateway paths.
  Full media/voice and live-account acceptance remain open. The wider Hermes
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

1. Actual Fedora 44 image and ISO build, installation and reboot into VT1 on
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

## Recovered owner on tty2 but no GUI on VT1

A real HP installation exposed a boot arbitration defect: tty2 owner
enrollment + recovery-code generation previously satisfied the general
`account_status.complete` flag without completing the separate graphical
normal-user profile. The desktop could be treated as eligible before the
mandatory profile; both systemd ExecConditions may still show old results
from the pre-enrollment boot.

The fixed boot gate now requires the dedicated root-owned 0600
`graphical-setup.json` receipt **as well as** owner/recovery readiness.
The receipt is only published after the normal observer display-name
profile and owner service checks succeed. Failed or malformed receipts
never unlock the desktop.

**Physical fallback if Xorg VT1 cannot display the wizard:** On the
machine's physical tty3, log in with the *existing owner account* and
run (sudo prompts for the owner password, never the locked root password):

```sh
sudo /usr/bin/haos-owner setup status
sudo /usr/bin/haos-owner setup name "Mein Anzeigename"
sudo /usr/bin/haos-owner setup finish
systemctl reboot
```

This fixed-action fallback is local-console only; the command rejects
SSH and other pseudo-terminals. The owner CLI checks the invoking kernel VT
reported by authenticated sudo as `SUDO_TTY`, because Fedora sudo `use_pty`
may give the child `/dev/pts/N` even if the owner really logged into tty3.
It also validates the enrolled owner UID and rejects arbitrary or symlinked TTY paths. It never edits administrator identities,
reissues recovery codes, opens a remote surface or exposes a root shell.
The initial owner and ten recovery codes MUST already exist and be saved.
On installations from **older ISO revisions**, the fallback subcommands
will not be present until that OS image is upgraded; do not instruct
users to run them on unchanged old bootc images.

For *current* older installs lacking the fix, reboot after tty2 enrollment
to re-evaluate the systemd startup conditions. If graphics are still black,
collect `systemctl status` of the two gated units and GUI journal
evidence; never bypass the gate or wipe the disk as a first step.

## Automatic graphical admin wizard on F1 during the first installed boot (HP bugfix)

An HP first-boot report identified a separate **activation-order** defect.
The previous native wizard was `WantedBy=graphical.target` alone, while
Anaconda can initially boot into `multi-user.target`. In addition, the
firstboot script could queue `graphical.target` from within its **incomplete**
firstboot service before `haos.initialize` had produced the credentials
and root state required by the two boot gates.

Fix: the dedicated VT1 native wizard is now `WantedBy=multi-user.target`,
`After=` and `Requires=herald-os-firstboot.service`. The initialization
script still installs `graphical.target` as the **next** boot default, but
does **not** activate it early during initialization. The first boot therefore
starts the root-only wizard on VT1 **automatically**, even when the first
Anaconda target is text-only. `greetd` remains blocked until the separate,
protected wizard completion receipt exists.

The existing owner console on tty2 is a recovery fallback, NOT a mandatory
firstboot step. A new user should be asked to create their administrator,
password and recovery codes directly within the automatically launched VT1
wizard. Unit tests assert the firstboot target ordering and prohibit starting
graphical.target prematurely. **The real installed HP/UEFI GPU + keyboard
acceptance is not complete merely because those tests pass.**

An older installed image does **not** gain this fix until a newer bootc
deployment is installed. Existing owner accounts/recovery codes are retained.
Never erase the disk just to re-run initial setup.

## Local VT mapping (pending physical HP acceptance)

- **Ctrl+Alt+F1**: native firstboot administrator wizard until the trusted setup receipt is published; normal HAOS desktop after completion/reboot.
- **Ctrl+Alt+F2**: independent owner enrollment and recovery console (never an automatic root shell).
- **Ctrl+Alt+F3**: physical user console and fixed `sudo /usr/bin/haos-owner setup` fallback.

The Xorg display identifier stays `:8` for isolation although the physical
virtual terminal is now VT1. A currently installed older bootc image still
uses its existing code; rebuild, install/stage, reboot, and inspect HP logs
before claiming this mapping is working on the real machine.


## Matrix owner setup and service integration (2026-10-25)

Matrix now has a reviewed HAOS text setup path alongside Telegram, Discord,
Slack and Mattermost: five of 22 adapters have owner provisioning and native
text integration. This supersedes the earlier private-only activation guards.
The public policy applies the same exact sender/room/root-thread/device rules
used by the native contracts. Complete canonical homeserver/user/device
credentials are required; a token alone or native extra overrides cannot be
published. The service constructs the guarded stable profile with current owner
authority and private raw storage, and closes it on service shutdown.

The graphical and owner CLI paths store tokens/recovery material privately,
expose exact route/capability/device choices, and never auto-approve a discovered
device. Public device discovery runs through the actual SDK as the gateway UID
with confirmed whoami and native self-signature validation; the owner must still
compare the fingerprint with the physical device. Credentials travel to this
short-lived helper only over stdin, not argv/environment. Discovery stops the
gateway until the owner restarts it. Unknown devices receive no result keys.
A fresh actual encrypted answer remains unreadable by an independent unapproved
SDK device of the same account, while the selected device can decrypt it.

Owner rotation/removal withdraws bindings and private configuration atomically;
recovery/account files remain retained. Removal is local HAOS withdrawal, not a
claim that the homeserver revoked its account token. Revoke obsolete tokens in
the Matrix account as appropriate. Stopped-owner inspection includes safe
profile/auth/rate/history status and retained-page counts; it reveals no message
content or private credentials. Offline input/outbox reconciliation accepts exact
Matrix event IDs, preserves original input age, and never sends on inspection.

In the GUI choose Matrix, enter a separate service account's existing access
token, canonical HTTPS homeserver, exact @user:server and stable device ID.
Optional recovery material must already exist; setup does not reset identities.
Join the service account to the intended rooms yourself. For each allowed sender,
enter @sender:server and !room ID, keep scope empty and choose the existing $root
thread or leave it empty for flat messages. Load signed devices, compare their
Ed25519 fingerprints out of band and explicitly stage the desired devices.
The signature also binds Curve25519. Then save the route and selected rights.
Plaintext defaults off and mentions default on. Restart the gateway after pairing.

Equivalent owner console setup (replace all example public IDs/key placeholders):

```sh
sudo haos-owner gateway setup matrix-main matrix
sudo haos-owner gateway matrix-devices matrix-main '@owner:example.org'
sudo haos-owner gateway pair phone matrix-main '@owner:example.org' '!room:example.org' \
  --identity personal --matrix-device PHONE ED25519_PUBLIC_BASE64 CURVE25519_PUBLIC_BASE64 \
  --capabilities create read
sudo haos-owner gateway start
```

The setup command asks for private material through protected input. Optional
`--allow-plaintext` and `--no-require-mention` are explicit Matrix exceptions;
`--thread '$root-event'` selects one existing root thread. Invalid or self-echo
service-account bindings are refused. No public webhook, automatic invite join,
interactive native tool approval or arbitrary plugin is enabled.

Local validation covers 1118 full/minimal tests with two existing skips, 40 real
root/UID/socket gateway cases, 165 actual native Matrix cases across ten probes,
13 regression probes for the existing gateway paths, and seven real Tk Matrix
handoff/layout cases at each of 1280x800 and 640x480. Existing complete GUI
fixtures also pass at both sizes. Build/CI require native account discovery and
GUI tests. Source-bound evidence:
`docs/evidence/2026-10-25/matrix-owner-integration-validation.json`.

These contracts use disposable accounts/keys and loopback HTTP. They confirm no
external Matrix delivery, physical device trust, installed service/boot or
release. Full media/voice, the remaining 17 adapters, Android, phone firstboot
and installed OS/artifact acceptance remain unfinished.


## SMS / Twilio gateway

The Gateways page now includes real SMS/Twilio setup: protected Auth Token, exact
Account SID/owned E.164 number, verified public HTTPS URL, private PEM import and
explicit public listener consent. Pair an exact sender/chat number and select
rights; image/document, voice, video and result-file approval are separate and
unchecked. Local speech must be configured before voice can be approved. Context
changes discard private inputs and pending approvals. Auth recheck, retained
inputs, API catch-up failures/refusals and uncertain outgoing attempts use the
existing owner recovery controls. See [SMS requirements and operation](GATEWAY-SMS.md).
No external message, public reachability or handset receipt is established by
saving configuration or by the Tk/loopback fixtures.
