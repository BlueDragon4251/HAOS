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

Actual lsblk metadata must resolve uniquely. Missing, ambiguous, unsupported and system/owner disks fail closed. Data partitions sharing the physical system disk are conservatively refused. Supported types: ext4/xfs/btrfs/vfat/ntfs3. Owner must unlock LUKS first and grant its filesystem identity. Missing/hotplug volumes need owner reconciliation.

Mounts use nodev,nosuid,noexec in the host namespace; the agent has no raw devices or policy API. A writable grant does not override existing POSIX permissions. HAOS never recursively takes ownership of personal data. QEMU ownership changes affect only serial-verified new fixture disks. A tested owner-approved ACL/idmapped solution remains required. Egress, network volumes and enforcing SELinux coverage are incomplete.
