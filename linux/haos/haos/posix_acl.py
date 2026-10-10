"""Validated Linux POSIX ACL xattr encoding shared by permission brokers."""

import struct

USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER = 1, 2, 4, 8, 16, 32
UNDEFINED = 0xFFFFFFFF


def decode(value):
    if len(value) < 28 or (len(value) - 4) % 8 or struct.unpack_from("<I", value)[0] != 2:
        raise PermissionError("unsupported POSIX ACL encoding")
    entries = [tuple(row) for row in struct.iter_unpack("<HHI", value[4:])]
    seen = set()
    for tag, rights, uid in entries:
        if (tag not in {USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER} or rights & ~7
                or (tag in {USER, GROUP}) != (uid != UNDEFINED) or (tag, uid) in seen):
            raise PermissionError("invalid POSIX ACL entry")
        seen.add((tag, uid))
    if not all((tag, UNDEFINED) in seen for tag in (USER_OBJ, GROUP_OBJ, OTHER)):
        raise PermissionError("incomplete POSIX ACL")
    if any(tag in {USER, GROUP} for tag, _, _ in entries) and (MASK, UNDEFINED) not in seen:
        raise PermissionError("extended POSIX ACL needs a mask")
    return entries


def encode(entries):
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *row) for row in sorted(entries, key=lambda row: (row[0], row[2])))
