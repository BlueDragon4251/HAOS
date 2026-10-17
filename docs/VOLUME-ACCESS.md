# Owner-approved volume access

The existing stable UUID/PARTUUID, current topology, protected-system-disk and
nodev/nosuid/noexec checks remain mandatory. Only the root policy service and
password-authenticated owner CLI can grant storage rights. Hermes receives no
root capabilities, raw devices, ACL journal or owner endpoint.

For ext4, XFS and Btrfs, preparation now adds a named agent ACL to existing regular
files and directories, without changing their owner/group. Full access grants
read/write and directory traversal, rename and deletion, including originally
foreign-owned 0600 files and 0700 directories. Sticky directory restrictions are
temporarily removed inside this explicitly approved whole data volume. Previously
masked other-user/group permissions remain masked when the ACL mask expands.
Read-only delegation adds read/traverse permissions and remounts the filesystem
kernel read-only before publishing it to the agent.

Root-private SQLite recovery journals under `/var/lib/haos-owner/volume-acls`
save original access/default ACLs and modes durably before mutation. Keys are
filesystem handles containing inode generations, allowing rename and preventing
deleted-inode replacement from receiving stale permissions. Symlinks are never
followed, nested mounts are rejected, and special files prevent a full grant.
Unsupported ACL/handle operations, immutable files, traversal over 100000 inodes
or incomplete preparation fail rather than publishing a nominal full grant.

New entries inherit the agent grant. Directories lacking a default ACL get a
private default ACL; POSIX defaults replace ordinary creator-umask behavior.
Cleanup restores saved original permission metadata, removes named agent grants
from new entries and preserves their owner/group and content. New directories may
retain private defaults. A later external chmod can withdraw an inherited mask;
refresh requires stopping execution and preparing again. Concurrent external
writers and arbitrary future permission changes are not a continuously enforced
ownership-bypass service.

Revocation still requires fully stopped Hermes/controller units and control-group
termination. ACL removal alone cannot revoke an already-open file descriptor.
Compiled grants are removed before cleanup; a restoration failure retains its
private recovery journal and still attempts unmount. An owner must reconcile a
missing/corrupted volume or nested mount before re-enabling it. Preserve recovery
journals together with their matching data volumes; existing encrypted staged
backups include this journal directory when present. General system recovery and
off-host backup acceptance remain separate requirements.

FAT/NTFS3 mounts use fixed agent uid/gid and private file/directory masks. Their
actual resulting mount flags/masks are verified, rather than merely accepting
mount exit status. New FAT/NTFS3 installed acceptance is still required.

The new guarded GitHub runner creates only fresh regular-file disk images, verifies
their loopback backing files and mounts, and runs real dropped-UID ACL tests on
ext4/XFS/Btrfs. It does not format physical disks. The matching QEMU guest now
prepares restrictive foreign-owner fixtures before granting access; the previous
test's agent chown is removed. All earlier sandbox/blocked-volume/readonly tests
remain. Exact runner and rebuilt-guest results are required before checking off
this requirement. Cloud scratch filesystems failed with EOPNOTSUPP and are not
reported as passing integration evidence.
