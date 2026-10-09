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

Initialization generates a unique key in `/etc/haos/backup-password`, never the process arguments or audit log. Key loading rejects symlinks, hardlinks and non-private ownership/modes. Preserve that key independently through an authenticated owner workflow; loss of the key cannot be repaired by generating another password. A local repository on the OS disk does not protect against failure/loss of that disk. External/off-host destinations and scheduled snapshots remain unfinished.

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
as possibly modified; inspect the inventory before retrying. There is no automatic
timer or remote destination yet. Current receipt compatibility was exercised with
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

Contracts follow [Restic backup/scripting](https://restic.readthedocs.io/en/stable/075_scripting.html) and [restore](https://restic.readthedocs.io/en/stable/050_restore.html) documentation.
