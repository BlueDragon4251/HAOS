# Tests

```sh
bash scripts/test-haos.sh
npm run sync-upstream
npm ci
npm run typecheck
npm test
npm run build
```

The owner-backup tests exercise actual root-owned directories and credentials. On a non-root development machine run the ordinary suite with `bash scripts/test-haos.sh --ignore=linux/haos/tests/test_backup.py`, then separately run `sudo /path/to/prepared/python -m pytest -q linux/haos/tests/test_backup.py`. CI executes both groups; exclusion from the ordinary account's invocation is not a skipped acceptance gate. The separate real Restic probe uses only freshly created temporary fixture files.

The observer-authority probe runs exclusively on the disposable CI runner. It creates one uniquely named fixture account, demonstrates a real inherited NOPASSWD root command, removes administrator groups/blank-password access and verifies that root commands and sudoedit fail. Only that account and its own two temporary sudo rules are removed afterward. CI first tightens the pre-existing hosted runner sudo rule to mode 0440 because strict full `visudo -c` rejected its inherited nonstandard permissions; production validation remains strict. Do not run the probe on a personal/production host. New image guest probes separately require the actual pre-session guard and observer denial, and recover a deleted fixture through the installed owner backup CLI; no success is inferred until their guest receipts exist.

HAOS unit setup uses Python 3.11, pytest 9.0.2, websockets 15.0.1; HAOS_TEST_PYTHON selects a prepared interpreter. Tests cover idempotency, deadlines, resource locks, ambiguous crash recovery, protocol framing and denied authority. Fake unit wires are not provider execution evidence.

Enrollment unit fixtures simulate root file identity and ownership changes while keeping real file modes, atomic registry writes and rollback assertions. They do not require the development account to own files as root. Foreign-owner, readable and symlinked enrollment locks must still fail before provisioning. The nftables validation-failure test uses fixed resolver input rather than trusting the developer machine's actual `/etc/resolv.conf`. Real ownership, password authentication and firewall enforcement remain separate probes.

Real probes:

```sh
python -m pytest -q linux/haos/probes/test_unix_control.py linux/haos/probes/test_kernel.py
systemd-analyze verify linux/haos/*.service
```

They require actual AF_UNIX/user namespaces, unavailable in scratch. GitHub Ubuntu CI loads the packaged bwrap-userns-restrict profile without disabling AppArmor globally. The production command runs under NoNewPrivileges and performs actual allowed/denied file and syscall operations.

QEMU adds installed-service health, native UI process presence, UI restart without backend PID change, multi-disk policy enforcement and a journal record across reboot. The persistence fixture is offline/cancelled, not a real provider/gateway mission. Syntax-checked harness is not success: require both acceptance JSON receipts and logs.

`haos-acceptance.yml` retests the latest completed, non-expired private image artifact on the working branch when the harness changes. It verifies the ISO checksum and manifest, uses the guest probe from that image's exact source commit, and records both the image and harness revisions. This avoids mistaking an older runtime's probe results for evidence about a newer runtime. Images must be ancestors of the harness revision. A completed image build can be reused even when its earlier installation test failed.

Outstanding acceptance includes authenticated model/Git/gateway missions, unknown sender denial, theme/watchdog rollback, installed-OS/off-host backup recovery, broken-update recovery, remote streaming and resource measurements. The local encrypted deleted-project restore and incorrect-key denial passed on the real CI runner at `88425fb` in [run `37839452538`](https://github.com/BlueDragon4251/HAOS/actions/runs/37839452538).

Before each installer/boot phase, `haos-qemu-runtime.py` initializes a diskless QEMU machine and requires a complete QMP handshake. Mode bits on `/dev/kvm` alone are insufficient: ACLs, cgroups or runner permissions may prevent KVM initialization, and availability may change between boots. If KVM fails, a separately verified multi-thread TCG runtime is used. Each phase records its acceleration and probe errors in `runtime-*.json`. Neither path bypasses guest assertions. Installer/boot limits are 120/30 minutes and the complete job is bounded to 210 minutes; a TCG timeout is a failed acceptance, not success.

`python -m pytest -q tests/e2e/test_qemu_runtime.py` covers denied/hung KVM, the TCG fallback, changing permissions and failed QMP initialization. These unit tests do not constitute real VM acceptance.

Run `37836993147` demonstrated a race: diskless KVM initialization succeeded, then the actual QEMU launch immediately lost permission. The launcher now also permits one verified TCG retry for an explicit KVM initialization failure, only if the serial log is absent/empty. Guest output, disk errors, signals and timeouts do not trigger replay. Actual launch return codes/errors are retained alongside probes in the phase evidence.

## Continuation on 2026-10-09

The real nftables boundary probe and owner enrollment probe are separate root-only disposable CI steps, not ordinary workstation tests. They create only fresh accounts and their own fixture rules. The owner probe additionally requires `GITHUB_ACTIONS=true` and `HAOS_DISPOSABLE_CI=1`, verifies real password installation, correct/incorrect sudo authentication, per-call authentication, denied arbitrary commands/environment override, and password absence in registry/audit. Neither probe has executed: GitHub billing blocks new jobs before any step. Never run account/firewall probes on a personal or production machine.

The actual frozen backend contract probe at `ab2e521` passed dependency CI and actual Fedora image builds: health, missing/wrong-token denial, child PID identity and durable session creation. It creates no provider turn. Mount identity checks at `e8dd0aa` passed service CI (87 units and six real probes). At owner code `8f2957f`, local checks passed 133 unit/regression tests, actual hostile Python-startup/package denial, real sudoers syntax and systemd/shell syntax. These source-specific results do not certify installed authentication/networking or the complete OS.

`haos_guest_diagnostics.py` runs only for root in a DMI/marker-verified disposable acceptance VM. Successful probes do nothing; failed probes print bounded, token-redacted service state and journals, then power off even when diagnostics fail. It records diagnostic-harness provenance separately from the matching image/guest protocol. Seven regression tests passed in real service CI at `19e73a9`. Earlier image `9e0d4a3` installed and booted but failed the backend health assertion; host timeout alone had hidden that failure.

Harness-only changes now reuse an image rather than rebuilding it. Actual image inputs, including bridge plugins and guest protocol, still trigger new builds. Future builds also upload a small separate metadata artifact containing manifest, ISO checksum, runtime backend receipt and inventories, avoiding multi-gigabyte downloads merely to inspect identity. An artifact ZIP digest is never an ISO checksum.

`linux/haos/probes/test_policy_access.py` runs as a separate required root filesystem fixture in CI. It changes no host accounts or disks. It reproduces the old 0077-umask failure, runs a process with a real non-root numeric UID/group against the actual trusted-policy reader, checks read-only authority and denies another group. Scratch maps only UID/GID 0, so its attempted chown returns EINVAL; this probe was not completed locally and is not silently skipped. The ordinary suite's identity-metadata simulations cover explicit mode application and refusal of mounted/symlinked/writable/foreign directories. Latest local result is 138 passed. Reuse `37878610539` is now completed failure with exact directory-permission evidence and prompt poweroff; no installed success is inferred.
