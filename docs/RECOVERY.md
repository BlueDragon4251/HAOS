# Owner recovery

The immutable haos-owner CLI works independently of Electron. On an installed test system:

```sh
sudo haos-owner stop
sudo haos-owner status
sudo journalctl -u haos-hermes -u haos-controller -u haos-policy
```

Stopping services terminates their cgroups, not earlier external effects. Inspect mission receipts, affected files/repos/downloads and external services. Preserve evidence. Post-dispatch ambiguity deliberately retains the mission lock.

After concrete inspection:

```sh
sudo haos-owner reconcile MISSION_ID --note 'Inspection evidence and decision'
sudo systemctl reset-failed haos-hermes haos-controller haos-policy
sudo haos-owner start
```

Reconciliation cancels the blocked mission with an owner receipt; it never invents completion. New submission requires inspection establishing safety. Missing UUIDs should be resolved, not replaced with raw paths.

The CLI requires both execution units to be fully inactive with zero main/control PIDs. Activating, deactivating, failed or unknown units are not accepted as stopped. Stop/reset and inspect them first. The systemd storage entrypoint is separately ordered before execution and after shutdown.

## Encrypted owner snapshots

The fixed local Restic repository is `/var/lib/haos-owner/backup/repository`. The owner CLI requires stopped execution units and authenticated root authority. It snapshots only the workspace, agent state, controller journal and HAOS configuration; `--one-file-system` prevents walking nested mounts. The repository/password and restored staging areas are root-private. No gateway/agent endpoint can invoke these owner operations.

```sh
sudo haos-owner stop
sudo haos-owner backup init
sudo haos-owner backup create
sudo haos-owner backup check
sudo haos-owner backup snapshots
sudo haos-owner backup restore FULL_64_CHARACTER_SNAPSHOT_ID
```

Initialization generates a unique key in `/etc/haos/backup-password`, never the process arguments or audit log. Key loading rejects symlinks, hardlinks and non-private ownership/modes. Preserve that key independently through an authenticated owner workflow; loss of the key cannot be repaired by generating another password. A local repository on the OS disk does not protect against failure/loss of that disk. External/off-host destinations remain unfinished.

Restore checks repository data and verifies the recovered files in a newly created directory below `/var/lib/haos-owner/backup/restores`. It leaves live state untouched; inspect and explicitly apply selected recovered files from the owner console. Interrupted restores retain an incomplete marker and never produce a success receipt. Partial backup exit codes also fail. Snapshot inventory returns exact identifiers, without exposing Restic's file names or host/user metadata.

## Explicit encrypted retention

The owner can preview bounded retention counts while execution is stopped:

```sh
sudo haos-owner backup retention --keep-last 7 --keep-daily 7 --keep-weekly 4 --keep-monthly 12
```

Only adding `--apply` deletes selected snapshots and prunes unreferenced encrypted
packs. The default is a dry run. Counts are validated and `--keep-last` must be at
least one. Restic selects only `haos-owner` snapshots, grouped by host and source
paths, so another tag and a different source group retain their snapshots. This
is a protection against policy scope errors, not authority for an untrusted caller:
the command still requires independent owner authentication and stopped services.

Before deletion the complete encrypted data is checked. Forget's JSON receipt,
prune and the final data check run separately; Restic's prune progress is not
mistaken for a JSON receipt. A final actual inventory must agree with retained and
removed identifiers. Responses/audit include identifiers and flags, never raw
Restic output, file names or credentials. A failure during application is audited
as possibly modified; inspect the inventory before retrying. Scheduled retention
also requires an explicit owner grant; remote destinations remain open. Current receipt compatibility was exercised with
Restic 0.18.0; the older deleted-project probe passed with 0.16.4. Restic 0.14's
short backup receipt is rejected rather than accepted as an exact snapshot ID.

The extended real probe verifies preview leaves all snapshots intact, application
preserves another tag/source group, retained data restores, and deliberate encrypted
pack corruption blocks both restore and retention. A second probe destroys only its
isolated configuration/mission/theme fixture, restores into staging, opens the real
SQLite store and checks integrity, mission identity/events/cancellation, configuration,
asset bytes/mode and an untouched neighbor. It leaves the damaged live fixture in
place. This is evidence for multi-component staged data recovery, **not** a restored
bootable system, account reconstruction, off-host media or update rollback. Observer
theme/plugin homes, provider/gateway private state and full owner identity recovery
still need complete snapshot/restore integration.

The CI probe uses an actual disposable Restic repository, deletes only its own fixture project, restores it, verifies bytes and permissions, checks a neighboring canary and rejects the wrong key. This passed with Restic 0.16.4 at `88425fb` in [run `37839452538`](https://github.com/BlueDragon4251/HAOS/actions/runs/37839452538). A green runner probe is distinct from installed-OS and whole-system recovery. Bootc rollback remains inherited architecture without a passed broken-update drill.

## Owner-configured scheduling

The immutable `haos-backup-schedule.service` reuses the same fixed local Restic
repository, source scope, key validation, integrity checks and retention. Its timer
is installed disabled. Configure it only through the independent owner flow:

```sh
sudo haos-owner stop
sudo haos-owner backup init
sudo haos-owner backup schedule daily
sudo haos-owner backup schedule-status
sudo systemctl start haos-backup-schedule.service
sudo haos-owner start
```

`weekly` is also supported; `schedule off` disables the timer. The timer checks
every 15 minutes after boot with bounded jitter; the durable last-success time
decides whether a snapshot is due. Clock rollback does not cause duplicate work.
Both execution units must be fully stopped. Busy/activating/deactivating execution
defers the snapshot without stopping a mission. **An always-running system will
defer until an owner maintenance stop**; general live filesystem snapshots are
still open; the separate mission-ledger scope below now supports live SQLite checkpoints. The oneshot orders before concurrent controller/Hermes starts.

Retention previews by default. Add `--prune` and bounded `--keep-last`,
`--keep-daily`, `--keep-weekly`, `--keep-monthly` counts when configuring the
schedule to expressly authorize future scoped deletion. At least one latest
snapshot per scope is always retained. No agent/gateway can enable the timer,
change destinations, initialize credentials or authorize retention.

A private nonblocking lock prevents concurrent scheduler/configuration work.
Modifying intent is fsynced before backup/prune. Lost receipts, process death or
modifying failures block automatic retries, including after reconfiguration.
Inspect encrypted snapshot inventory/data from the owner console, then explicitly
clear the attempt while execution is stopped:

```sh
sudo haos-owner backup schedule-clear --note 'Inspection evidence without secrets' --confirm-inspected
```

This records a digest of the note and never deletes a snapshot or claims completion.
Missing keys/media and failed read-only integrity checks report unavailable. Logs
contain fixed phase/reason/identifier receipts, with no Restic output or key values.
The root oneshot has read-only sources, no network, private devices, a bounded
process group, memory/CPU limits and a six-hour deadline.

Actual Restic tests cover encrypted scheduling/restore, durable due state, explicit
prune versus preview, runtime deferral, missing key, configuration/lock attacks,
concurrency and lost modifying receipts. The installed QEMU gate now requires the
actual timer/job and restoration of its snapshot; matching run receipts remain
required before claiming installed scheduling. No full OS recovery is implied.

Contracts follow [Restic backup/scripting](https://restic.readthedocs.io/en/stable/075_scripting.html) and [restore](https://restic.readthedocs.io/en/stable/050_restore.html) documentation.

### Consistent live mission-ledger scope

Owners can now select a narrower scope that runs while the controller and Hermes
remain active:

```sh
# Initialize the encrypted repository/key once during owner maintenance first.
sudo haos-owner backup schedule daily --scope mission-ledger
sudo haos-owner backup schedule-status
```

The production root scheduler uses SQLite's online backup API through a normal
read-only, WAL-aware connection to the fixed controller database. It never copies
active WAL/SHM files, uses `immutable=1`, stops a mission or gives an agent a backup
endpoint. It verifies source ownership, all ancestors, file/link types, database
version, integrity/foreign keys and source inode stability. Work is bounded to
512 MiB, a 30-second checkpoint deadline and small page/cache batches; existing
systemd CPU/RAM/process/I/O limits remain in force. An actual read-only bind-mount
probe verifies that committed WAL data remains available under the production
read-only source restriction.

Only a validated standalone database and a bounded checksum/scope manifest are
exported into the fixed root-private `/var/lib/haos-owner/live-mission-checkpoint`
scope. Restic encrypts that scope; its source path stays stable for retention.
The online API gives a transaction-consistent database at the checkpoint's point
in time, not a globally synchronized system/files snapshot. Exports are prepared
under the scheduler's private lock before Restic is called. Failure after any
modifying intent remains blocked for owner inspection, including an interrupted
export/receipt. It must not be mistaken for a successful new backup. Scope changes
cannot clear blocked attempts; changing an idle scope resets its due receipt
without deleting existing repository snapshots.

This scope contains missions, events, resource locks and controller-owned gateway,
GUI and provider ledger tables. It excludes workspace files, upstream sessions,
owner identities/credentials, observer themes/plugins and system configuration.
Use `--scope system` for the existing full configured source list during an owner
maintenance stop. A stopped whole-system snapshot and a live ledger checkpoint
are separate recovery scopes. Enabling the live scope does not complete general
live backup or full bootable-system recovery.

Restore remains owner-authorized and staged with the existing stopped-runtime
requirement. Verify `checkpoint.json` against the restored `missions.db` and
inspect identities, effects and recovery state before any live replacement.
A saved running/dispatched mission becomes blocked when the real controller store
recovers it; it is never blindly resubmitted. Root probes exercise an actual
separate WAL writer, encrypted scheduled backup/staged restore, atomic transaction
pairs and real recovery refusing redispatch, with the original writer continuing.
New installed-QEMU assertions verify the hardened systemd job, unchanged live
runtime PIDs and encrypted ledger restore; they remain pending until their matching
source/image run provides actual receipts.
