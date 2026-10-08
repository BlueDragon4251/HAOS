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
sudo haos-owner backup restore FULL_64_CHARACTER_SNAPSHOT_ID
```

Initialization generates a unique key in `/etc/haos/backup-password`, never the process arguments or audit log. Preserve that key independently through an authenticated owner workflow; loss of the key cannot be repaired by generating another password. A local repository on the OS disk does not protect against failure/loss of that disk. External/off-host destinations, scheduled snapshots and retention remain unfinished.

Restore checks repository data and verifies the recovered files in a newly created directory below `/var/lib/haos-owner/backup/restores`. It leaves live state untouched; inspect and explicitly apply selected recovered files from the owner console. Interrupted restores retain an incomplete marker and never produce a success receipt. Partial backup exit codes also fail. There is no automatic prune/delete operation.

The CI probe uses an actual disposable Restic repository, deletes only its own fixture project, restores it, verifies bytes and permissions, checks a neighboring canary and rejects the wrong key. This passed with Restic 0.16.4 at `88425fb` in [run `37839452538`](https://github.com/BlueDragon4251/HAOS/actions/runs/37839452538). A green runner probe is distinct from installed-OS and whole-system recovery. Bootc rollback remains inherited architecture without a passed broken-update drill.

Contracts follow [Restic backup/scripting](https://restic.readthedocs.io/en/stable/075_scripting.html) and [restore](https://restic.readthedocs.io/en/stable/050_restore.html) documentation.
