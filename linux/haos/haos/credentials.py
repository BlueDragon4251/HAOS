"""Read credentials only when actual DAC/ACL permissions isolate the caller."""

import errno
import os
import stat

from .posix_acl import GROUP, GROUP_OBJ, MASK, OTHER, USER, decode


def private_credential(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        uid = os.geteuid()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, uid}
                or info.st_nlink != 1 or info.st_mode & 0o117 or info.st_size > 32768):
            raise PermissionError("untrusted provider service credential")
        try:
            acl = decode(os.getxattr(fd, "system.posix_acl_access"))
        except OSError as error:
            if error.errno not in {errno.ENODATA, errno.ENOTSUP}:
                raise
            acl = None
        if acl is None:
            if info.st_mode & 0o077:
                raise PermissionError("provider credential grants group or other access")
        else:
            # systemd uses a root-owned 0400 file with a named service-UID read
            # ACL. Its mask appears as mode 0440, but the owning group has NO
            # access. Never accept ordinary 0440/0640 group-readable secrets.
            mask = next((rights for tag, rights, _ in acl if tag == MASK), 7)
            for tag, rights, identity in acl:
                if tag in {GROUP_OBJ, GROUP} and rights & mask:
                    raise PermissionError("provider credential ACL grants group access")
                if tag == OTHER and rights:
                    raise PermissionError("provider credential ACL grants other access")
                if tag == USER and rights & mask:
                    if identity not in {0, uid} or rights & mask & ~4:
                        raise PermissionError("provider credential ACL grants unauthorized user access")
        with os.fdopen(fd) as stream:
            fd = -1
            value = stream.read(32769)
        if len(value.encode()) > 32768:
            raise PermissionError("provider credential changed beyond its size limit")
        return value
    finally:
        if fd >= 0:
            os.close(fd)
