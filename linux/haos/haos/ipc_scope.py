"""Kernel-enforced isolation from abstract Unix sockets outside the agent domain.

Filesystem Unix sockets remain subject to the existing mount/peer policy. No
filesystem or TCP rights are granted here. Descendants inherit this restriction.
"""
import ctypes
import errno
import platform
import sys

MINIMUM_ABI = 6
ABSTRACT_UNIX_SOCKET = 1


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64),
                ("scoped", ctypes.c_uint64)]


def kernel():
    # These syscall numbers are shared by the supported Fedora architectures.
    # Never execute a guessed syscall on an unknown architecture or operating OS.
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise OSError(errno.ENOTSUP, "abstract Unix isolation requires a supported Linux kernel")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.restype = ctypes.c_int
    return libc


def restrict_abstract_sockets():
    """Fail closed before runtime startup if the required kernel scope is absent."""
    libc = kernel()
    abi = libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    if abi < MINIMUM_ABI:
        raise OSError(ctypes.get_errno() if abi < 0 else errno.ENOTSUP,
                      "Landlock ABI 6 or newer is required for abstract Unix isolation")
    attributes = Ruleset(0, 0, ABSTRACT_UNIX_SOCKET)
    descriptor = libc.syscall(444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0)
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "cannot create the abstract Unix isolation scope")
    try:
        # NoNewPrivileges is already mandatory in systemd/bwrap; also enforce it
        # at this boundary rather than depending on the launcher's environment.
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "cannot preserve no-new-privileges")
        if libc.syscall(446, descriptor, 0) != 0:
            raise OSError(ctypes.get_errno(), "cannot enter the abstract Unix isolation scope")
    finally:
        # The domain lives on in the task, not in a retained authorization FD.
        import os
        os.close(descriptor)
    return int(abi)
