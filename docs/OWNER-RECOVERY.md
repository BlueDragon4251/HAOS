# Independent owner onboarding and recovery

The immutable `haos-recovery` console runs on **tty2**, separately from Hermes and Electron.
Switch with Ctrl+Alt+F2; return to the Herald session with Ctrl+Alt+F1. It provides fixed actions,
never a root shell or an arbitrary command/path API. Its stdin/stdout/stderr go to the local TTY,
not the journal. Device access, namespaces, network families, capabilities, tasks and memory are
restricted. Agent tools have no access to this TTY or the recovery store.

On a fresh installation it asks for a new owner account and a strong password twice using the
same actual enrollment CLI implementation. Existing accounts cannot be repurposed. A second
onboarding attempt fails under the enrollment lock once any owner exists, including a prompt
opened before another console completed setup. Execution is stopped during onboarding.

After successful enrollment, ten 256-bit recovery codes are displayed once at the console.
**Keep them separately from the computer and its backups.** Only salted hashes are written to
the root-private store. Do not put codes into a chat, repository or screenshot. Generating new
codes revokes all previous ones:

```sh
sudo haos-owner recovery-codes OWNER_ACCOUNT
```

Hermes, controller and gateways require the root-only `haos-owner-ready` check. They cannot
start before a separate enrolled owner and recovery codes exist. The console remains available
when those services or the shell fail. Existing development installations need their owner to
enroll and issue codes before starting the updated services.

If the owner loses the password, the independent console accepts the exact enrolled account
and a single-use recovery code. It can reset that owner's password or stop execution services.
It validates the persistent UID/account relationship. Consumption is synchronized and durably
committed **before** the action, so a crash or repeated input never reuses the code. Incorrect
codes produce persistent exponential delay, capped at five minutes. A consumed code is spent
even if a later reset fails. Return to password-authenticated `haos-owner` administration after
reset; recovery authentication does not create unrestricted sudo.

There is no default administrator password, automatic root login, remote recovery endpoint or
fallback based on model/chat output. If both password and recovery codes are lost, this mechanism
cannot authenticate the owner. Offline full-system recovery and protection against physical
boot/media tampering remain separate requirements; Secure Boot is not claimed.

## Verification

Seven actual root fixture probes passed in an offline container: private non-plaintext storage,
restart persistence, used-code denial, wrong-code backoff, rotation revocation, concurrent
single-consumption and symlink/public/foreign/corrupt-store refusal. Ordinary service suite:
145 tests. QEMU/diagnostic/privileged-fixture guard suite: 27 tests.

The exact-source guest harness now requires real interactive owner enrollment, PAM/sudo after
both boots, code issuance, actual independent-console password recovery, rejection of the old
password and rejection of a reused code. Its random password/code are in a private guest directory
outside collected artifacts and removed after boot two. These are **pending installed assertions**
until the matching ISO workflow returns both receipts; source presence is not acceptance.

A graphical owner wizard/lock screen, recovery-media workflow and complete PAM/Polkit/SELinux
review are still open. This console supplies the independent authenticated fallback and initial
local enrollment path without claiming those additional features.
