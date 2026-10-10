# Storage policy

Root-owned `/etc/haos/volumes.json` version 1 accepts entries containing exactly id/mode. IDs are UUID:<filesystem UUID> or PARTUUID:<partition UUID>. Unknown volumes are blocked. Compiled grants live at `/run/haos-policy/sandbox.json`; mount keys are SHA-256 of the identifier.

| Mode | Enforcement |
| --- | --- |
| blocked | No agent-visible mount |
| read-only | Root read-only mount and read-only bind |
| full-data-access | Read/write mount/bind, subject to POSIX ownership/ACLs |
| system-managed | Reserved owner classification; never agent-visible |

Owner operations on an installed development guest:

```sh
sudo haos-owner stop
sudo haos-owner status
sudo haos-owner volume UUID:your-filesystem-uuid read-only
sudo haos-owner start
```

Actual lsblk metadata must resolve uniquely. Ambiguous, unsupported and system/owner disks fail closed. Data partitions sharing the physical system disk are conservatively refused. Supported types: ext4/xfs/btrfs/vfat/ntfs3. Owner must unlock LUKS first and grant its filesystem identity.

If a previously granted UUID/PARTUUID is not connected during stopped-runtime preparation, its owner policy remains intact but no mount or sandbox bind is published for it. The read-only compiled plan records `unavailable` with reason `not-connected`; `sudo haos-owner status` includes that actual published plan. Other safe volumes and Hermes can start. An old mount or symlink at the absent identity's broker destination is still refused, as are duplicate identities, an unsupported connected device or a protected system disk. Explicit new owner grants still require the actual device to be present.

Reconnecting a device does not expand a running agent namespace. Stop execution, inspect the stable identity and prepare/start again to make an existing grant available. Live USB removal/reinsertion, automatic hotplug refresh and complete old-process revocation across such events remain separate unfinished gates. Local contracts cover absence/reconnection selection and all unsafe cases; an isolated root probe uses actual `lsblk`, publication and a dropped service UID without modifying any device. Matching installed/hotplug acceptance remains required.

After mounting, `findmnt` must report the exact target, filesystem, selected UUID/PARTUUID, kernel major:minor device identity, `nodev,nosuid,noexec` and requested read-only/read-write mode. The block inventory is read again before grants are published; changed, ambiguous or newly protected topology fails closed. Preparation invalidates old compiled grants first. A failed check rolls back newly created mounts and leaves no stale sandbox configuration. Nine regression tests for this behavior passed in service CI at `e8dd0aa`, run `37879539364`; actual installed/hotplug receipts remain required.

Mounts use nodev,nosuid,noexec in the host namespace; the agent has no raw devices or policy API. A writable grant does not override existing POSIX permissions. HAOS never recursively takes ownership of personal data. QEMU ownership changes affect only serial-verified new fixture disks. A tested owner-approved ACL/idmapped solution remains required. Egress, network volumes and enforcing SELinux coverage are incomplete.

Runtime directory creation explicitly applies 0750 to a verified root-owned inode after assigning the dedicated agent group. `mkdir` mode alone is insufficient under the policy service's restrictive umask: it caused the confirmed installed backend failure in reuse `37878610539`. Compiled policy stays 0640 and never grants the service write authority. Unexpected mounts, symlinks, non-root ownership or group/world-writable directories are refused before metadata changes. Local mode regressions passed; the actual dropped-UID filesystem and rebuilt-guest probes remain pending behind environment/Billing limits.
