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

Bootc rollback is inherited architecture, not a passed HAOS broken-update drill. Restic provisioning, encrypted backup and successful lost-project restore are incomplete.
