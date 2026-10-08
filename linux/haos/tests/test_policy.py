import hashlib
import json

import pytest

from haos.policy import resolve_volume, validate_policy
from haos.sandbox import command, trusted_json


def test_policy_uses_stable_identity_and_cannot_inject_paths_or_mount_options():
    identifier = "UUID:abcd-1234"
    grants = validate_policy({"version": 1, "volumes": [{"id": identifier, "mode": "read-only"}]})
    assert grants[0]["key"] == hashlib.sha256(identifier.encode()).hexdigest()
    for entry in ({"id": "../../dev/sda", "mode": "full-data-access"},
                  {"id": identifier, "mode": "root"},
                  {"id": identifier, "mode": "read-only", "path": "/"}):
        with pytest.raises(ValueError):
            validate_policy({"version": 1, "volumes": [entry]})
    with pytest.raises(ValueError):
        validate_policy({"version": 1, "volumes": [{"id": identifier, "mode": "read-only"}] * 2})


def test_missing_duplicate_and_system_disk_identities_are_denied():
    system = {"path": "/dev/sda1", "type": "part", "fstype": "btrfs", "uuid": "system", "mountpoints": ["/"], "ancestors": ("/dev/sda",)}
    data = {"path": "/dev/sdb1", "type": "part", "fstype": "ext4", "uuid": "data", "mountpoints": [], "ancestors": ("/dev/sdb",)}
    devices = [system, data]
    assert resolve_volume("UUID:data", devices)["path"] == data["path"]
    for identifier, inventory in (("UUID:missing", devices), ("UUID:system", devices),
                                  ("UUID:data", devices + [{**data, "path": "/dev/sdc1"}]),
                                  ("UUID:data", [system, {**data, "ancestors": ("/dev/sda",)}])):
        with pytest.raises(PermissionError):
            resolve_volume(identifier, inventory)


def test_sandbox_binds_only_explicit_grants_and_never_inherits_parent_authority():
    grants = validate_policy({"version": 1, "volumes": [
        {"id": "UUID:ro", "mode": "read-only"}, {"id": "UUID:rw", "mode": "full-data-access"},
        {"id": "UUID:no", "mode": "blocked"}, {"id": "UUID:sys", "mode": "system-managed"}]})
    args = command(grants, 3, certificates=["/etc/hosts"])
    for grant, flag in zip(grants[:2], ("--ro-bind", "--bind")):
        index = args.index(f"/run/haos-volumes/{grant['key']}")
        assert args[index - 1] == flag
    assert all(f"/run/haos-volumes/{g['key']}" not in args for g in grants[2:])
    assert "--clearenv" in args and "--disable-userns" in args and "--cap-drop" in args
    assert "HERMES_PARENT_PID" not in args and "--ro-bind-data" in args
    assert "HERMES_DASHBOARD_SESSION_TOKEN" not in args
    assert args[-1] == "/usr/lib/haos/haos/launch.py"
    for raw in ("/", "/etc", "/run", "/home", "/var", "/sys", "/dev"):
        assert not any(args[i:i+2] == [flag, raw] for i in range(len(args)) for flag in ("--bind", "--ro-bind", "--dev-bind"))
    with pytest.raises(ValueError):
        command(grants, 0, certificates=[])
    with pytest.raises(ValueError):
        command(grants, 3, certificates=["/etc/shadow"])


def test_group_writable_or_symlinked_authority_is_rejected(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"version": 1}))
    tmp_path.chmod(0o770)
    with pytest.raises(PermissionError):
        trusted_json(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(PermissionError):
        trusted_json(link)
