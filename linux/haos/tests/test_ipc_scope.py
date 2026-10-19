import ctypes
import errno
import os

import pytest

from haos import ipc_scope, launch


class Kernel:
    def __init__(self, abi=6, create=True, enter=True, privileges=True):
        self.abi, self.create, self.enter, self.privileges = abi, create, enter, privileges
        self.calls = []
        self.fd = None

    def syscall(self, number, *args):
        self.calls.append((number, args))
        if number == 444 and len(args) == 3 and isinstance(args[0], ctypes.c_void_p):
            assert args[1].value == 0 and args[2].value == 1
            return self.abi
        if number == 444:
            attributes = ctypes.cast(args[0], ctypes.POINTER(ipc_scope.Ruleset)).contents
            assert attributes.handled_access_fs == attributes.handled_access_net == 0
            assert attributes.scoped == 1 and args[1:] == (24, 0)
            if not self.create:
                ctypes.set_errno(errno.EPERM)
                return -1
            self.fd = os.open('/dev/null', os.O_RDONLY)
            return self.fd
        assert number == 446 and args == (self.fd, 0)
        if not self.enter:
            ctypes.set_errno(errno.EPERM)
            return -1
        return 0

    def prctl(self, *args):
        self.calls.append(('prctl', args))
        assert args == (38, 1, 0, 0, 0)
        if not self.privileges:
            ctypes.set_errno(errno.EPERM)
            return -1
        return 0


@pytest.mark.parametrize('abi', [6, 10])
def test_scope_has_no_filesystem_network_grants_and_closes_descriptor(monkeypatch, abi):
    kernel = Kernel(abi)
    monkeypatch.setattr(ipc_scope, 'kernel', lambda: kernel)
    assert ipc_scope.restrict_abstract_sockets() == abi
    assert [call[0] for call in kernel.calls] == [444, 444, 'prctl', 446]
    with pytest.raises(OSError):
        os.fstat(kernel.fd)


@pytest.mark.parametrize('abi', [-1, 0, 4, 5])
def test_missing_kernel_scope_never_continues_unrestricted(monkeypatch, abi):
    kernel = Kernel(abi)
    monkeypatch.setattr(ipc_scope, 'kernel', lambda: kernel)
    with pytest.raises(OSError, match='ABI 6'):
        ipc_scope.restrict_abstract_sockets()
    assert len(kernel.calls) == 1


@pytest.mark.parametrize('failure', ['create', 'enter', 'privileges'])
def test_failed_setup_never_claims_scope_and_closes_any_created_descriptor(monkeypatch, failure):
    kernel = Kernel(**{failure: False})
    monkeypatch.setattr(ipc_scope, 'kernel', lambda: kernel)
    with pytest.raises(OSError):
        ipc_scope.restrict_abstract_sockets()
    if kernel.fd is not None:
        with pytest.raises(OSError):
            os.fstat(kernel.fd)
    if failure == 'privileges':
        assert not any(number == 446 for number, _ in kernel.calls)


@pytest.mark.parametrize('system,architecture', [('darwin', 'x86_64'), ('linux', 'riscv64')])
def test_unknown_platform_never_uses_unverified_syscall_numbers(monkeypatch, system, architecture):
    monkeypatch.setattr(ipc_scope.sys, 'platform', system)
    monkeypatch.setattr(ipc_scope.platform, 'machine', lambda: architecture)
    monkeypatch.setattr(ipc_scope.ctypes, 'CDLL', lambda *a, **kw: pytest.fail('unverified kernel call'))
    with pytest.raises(OSError):
        ipc_scope.kernel()


def test_launcher_refuses_credentials_and_exec_before_failed_isolation(monkeypatch):
    def denied():
        raise OSError(errno.ENOSYS, 'scope unavailable')
    monkeypatch.setattr(ipc_scope, 'restrict_abstract_sockets', denied)
    monkeypatch.setattr(launch.Path, 'read_text', lambda *a, **kw: pytest.fail('credential read before scope'))
    monkeypatch.setattr(launch.os, 'execv', lambda *a: pytest.fail('unrestricted runtime launch'))
    with pytest.raises(OSError, match='unavailable'):
        launch.main()
