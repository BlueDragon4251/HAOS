"""Owner-authorized POSIX ACL grants with private, generation-aware recovery."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
import struct

from .enrollment import protected_directory
from .posix_acl import USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER, UNDEFINED, decode, encode

ACCESS = "system.posix_acl_access"
DEFAULT = "system.posix_acl_default"
MAX_INODES = 100000


def _get(fd, name):
    try:
        return os.getxattr(fd, name)
    except OSError as error:
        if error.errno == errno.ENODATA:
            return None
        raise


def _set(fd, name, value):
    if value is not None:
        os.setxattr(fd, name, value)
    else:
        try:
            os.removexattr(fd, name)
        except OSError as error:
            if error.errno != errno.ENODATA:
                raise


def _base(mode):
    return [(USER_OBJ, (mode >> 6) & 7, UNDEFINED), (GROUP_OBJ, (mode >> 3) & 7, UNDEFINED), (OTHER, mode & 7, UNDEFINED)]


def add_user(value, mode, owner, uid, rights):
    entries = decode(value) if value is not None else _base(mode)
    old_mask = next((p for t, p, _ in entries if t == MASK), 7)
    result = []
    for tag, permission, identity in entries:
        if tag == MASK or (tag == USER and identity == uid):
            continue
        # Expanding the mask must not give previously masked users/groups rights.
        if tag in {USER, GROUP, GROUP_OBJ}:
            permission &= old_mask
        if tag == USER_OBJ and owner == uid:
            permission |= rights
        result.append((tag, permission, identity))
    result.extend([(USER, rights, uid), (MASK, 7, UNDEFINED)])
    return encode(result)


def remove_user(value, uid):
    if value is None:
        return None
    entries = decode(value)
    return encode([row for row in entries if not (row[0] == USER and row[2] == uid)])


class _Handle(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint), ("kind", ctypes.c_int), ("data", ctypes.c_ubyte * 128)]


def inode_handle(fd):
    """An inode number alone is unsafe after deletion/reuse or a reboot."""
    library = ctypes.CDLL(None, use_errno=True)
    handle, mount = _Handle(), ctypes.c_int()
    handle.size = 128
    if library.name_to_handle_at(fd, b"", ctypes.byref(handle), ctypes.byref(mount), 0x1000) != 0:
        raise OSError(ctypes.get_errno(), "filesystem cannot provide generation-aware ACL recovery")
    if not 0 < handle.size <= 128:
        raise PermissionError("invalid filesystem inode handle")
    return struct.pack("<i", handle.kind) + bytes(handle.data[:handle.size])


def _mount_id(fd):
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise PermissionError("cannot verify volume mount identity")


def walk(root, *, skip_special=False):
    """Pinned no-follow descriptors; never enter a symlink or nested mount."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    mount, device = _mount_id(root_fd), os.fstat(root_fd).st_dev
    visited = set()

    def visit(fd):
        info = os.fstat(fd)
        if info.st_dev != device or _mount_id(fd) != mount:
            raise PermissionError("nested mounts are excluded from an ACL grant")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise PermissionError("special files are excluded from a full-access grant")
        handle = inode_handle(fd)
        if handle in visited:
            return
        if len(visited) >= MAX_INODES:
            raise PermissionError("volume ACL traversal exceeds its explicit safety limit")
        visited.add(handle)
        yield fd, info, handle
        if stat.S_ISDIR(info.st_mode):
            for name in os.listdir(fd):
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode):
                    continue
                if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)):
                    if skip_special:
                        continue
                    raise PermissionError("special files are excluded from a full-access grant")
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if stat.S_ISDIR(before.st_mode):
                    flags |= os.O_DIRECTORY
                child = os.open(name, flags, dir_fd=fd)
                try:
                    current = os.fstat(child)
                    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                        raise PermissionError("volume changed during ACL traversal")
                    yield from visit(child)
                finally:
                    os.close(child)

    try:
        yield from visit(root_fd)
    finally:
        os.close(root_fd)


class Journal:
    def __init__(self, path: Path, identity: str, uid: int):
        if os.geteuid() != 0 or type(uid) is not int or not 0 < uid < UNDEFINED:
            raise PermissionError("ACL delegation requires a root broker and separate agent UID")
        protected_directory(path.parent)
        self.path, self.uid = path, uid
        self.lock = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.db = None
        try:
            self._private(self.lock)
            fcntl.flock(self.lock, fcntl.LOCK_EX)
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                self._private(fd)
            finally:
                os.close(fd)
            # Rollback journals stay in a root-private directory. No WAL files
            # or file contents enter the agent namespace or general audit log.
            self.db = sqlite3.connect(path)
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("CREATE TABLE IF NOT EXISTS authority(identity TEXT, uid INTEGER)")
            self.db.execute("CREATE TABLE IF NOT EXISTS original(handle BLOB PRIMARY KEY, access BLOB, defaults BLOB, mode INTEGER)")
            authority = self.db.execute("SELECT identity,uid FROM authority").fetchall()
            if not authority:
                self.db.execute("INSERT INTO authority VALUES(?,?)", (identity, uid))
                self.db.commit()
            elif authority != [(identity, uid)]:
                raise PermissionError("ACL recovery journal identity differs from owner authority")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _private(fd):
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
            raise PermissionError("ACL journal and lock must be root-private regular files")

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def grant(self, root, *, writable=True):
        count = 0
        for fd, info, handle in walk(root):
            access = _get(fd, ACCESS)
            defaults = _get(fd, DEFAULT) if stat.S_ISDIR(info.st_mode) else None
            # Persist the original rights BEFORE any mutation, including sticky
            # directories. Handles include inode generations and survive rename.
            self.db.execute("INSERT OR IGNORE INTO original VALUES(?,?,?,?)",
                            (handle, access, defaults, stat.S_IMODE(info.st_mode)))
            self.db.commit()
            directory = stat.S_ISDIR(info.st_mode)
            if writable and directory and info.st_mode & stat.S_ISVTX:
                os.fchmod(fd, stat.S_IMODE(info.st_mode) & ~stat.S_ISVTX)
            rights = (7 if writable else 5) if directory else (6 if writable else 4)
            _set(fd, ACCESS, add_user(access, info.st_mode, info.st_uid, self.uid, rights))
            if writable and directory:
                # Without an existing default ACL, new entries start private.
                # A default ACL necessarily replaces the creator's umask rules.
                base = defaults if defaults is not None else encode(_base(0o700))
                _set(fd, DEFAULT, add_user(base, 0o700, UNDEFINED, self.uid, 7))
            os.fsync(fd)
            count += 1
        return count

    def restore(self, root):
        count = 0
        for fd, info, handle in walk(root, skip_special=True):
            row = self.db.execute("SELECT access,defaults,mode FROM original WHERE handle=?", (handle,)).fetchone()
            if row:
                _set(fd, ACCESS, row[0])
                if stat.S_ISDIR(info.st_mode):
                    _set(fd, DEFAULT, row[1])
                os.fchmod(fd, row[2])
            else:
                # Entries created while delegated have no original snapshot;
                # remove the agent's inherited named grants without chowning.
                _set(fd, ACCESS, remove_user(_get(fd, ACCESS), self.uid))
                if stat.S_ISDIR(info.st_mode):
                    _set(fd, DEFAULT, remove_user(_get(fd, DEFAULT), self.uid))
            os.fsync(fd)
            count += 1
        self.db.execute("DELETE FROM original")
        self.db.commit()
        return count
