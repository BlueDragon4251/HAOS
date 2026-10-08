# Tests

```sh
bash scripts/test-haos.sh
npm run sync-upstream
npm ci
npm run typecheck
npm test
npm run build
```

HAOS unit setup uses Python 3.11, pytest 9.0.2, websockets 15.0.1; HAOS_TEST_PYTHON selects a prepared interpreter. Tests cover idempotency, deadlines, resource locks, ambiguous crash recovery, protocol framing and denied authority. Fake unit wires are not provider execution evidence.

Real probes:

```sh
python -m pytest -q linux/haos/probes
systemd-analyze verify linux/haos/*.service
```

They require actual AF_UNIX/user namespaces, unavailable in scratch. GitHub Ubuntu CI loads the packaged bwrap-userns-restrict profile without disabling AppArmor globally. The production command runs under NoNewPrivileges and performs actual allowed/denied file and syscall operations.

QEMU adds installed-service health, native UI process presence, UI restart without backend PID change, multi-disk policy enforcement and a journal record across reboot. The persistence fixture is offline/cancelled, not a real provider/gateway mission. Syntax-checked harness is not success: require both acceptance JSON receipts and logs.

Outstanding acceptance includes authenticated model/Git/gateway missions, unknown sender denial, theme/watchdog rollback, backups, broken-update recovery, remote streaming and resource measurements.
