"""Owner fixture provisioning must fail before any mutation outside a marked guest."""

import importlib.util
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "linux/haos"))
spec = importlib.util.spec_from_file_location("guest_owner_probe", Path(__file__).with_name("haos_guest.py"))
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


@pytest.mark.parametrize("uid,product,owner,mode", [
    (1000, "haos-acceptance", 0, stat.S_IFREG | 0o644),
    (0, "actual-workstation", 0, stat.S_IFREG | 0o644),
    (0, "haos-acceptance", 1000, stat.S_IFREG | 0o644),
    (0, "haos-acceptance", 0, stat.S_IFLNK | 0o777),
    (0, "haos-acceptance", 0, stat.S_IFREG | 0o666),
])
def test_owner_provisioning_cannot_mutate_an_unmarked_or_forged_guest(monkeypatch, uid, product, owner, mode):
    monkeypatch.setattr(guest.os, "geteuid", lambda: uid)
    monkeypatch.setattr(Path, "read_text", lambda self: product)
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_uid=owner, st_mode=mode))
    monkeypatch.setattr(guest.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("untrusted guest spawned root enrollment"))
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: pytest.fail("untrusted guest created owner credentials"))
    with pytest.raises(PermissionError):
        guest.owner_authentication_proof(first_boot=True)


def test_private_acceptance_credential_is_excluded_from_artifact_scope():
    # The executable harness only serializes proof flags into acceptance receipts.
    source = Path(guest.__file__).read_text()
    assert 'private = Path("/var/lib/haos-owner-ci")' in source
    assert 'secret_path = ROOT / "owner-auth-fixture.json"' not in source
