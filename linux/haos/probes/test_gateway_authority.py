"""Actual owner-protected files in root-owned disposable directories, never host config."""

import copy
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.gateway_setup import load, persist


def test_owner_credentials_and_pairing_are_persisted_with_separate_modes(tmp_path):
    assert os.geteuid() == 0, "run this explicit root-authority fixture as root"
    policy = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}], "bindings": []}
    credentials = {"connectors": {"first": {"token": "disposable-fixture-credential"}}}
    persist(policy, credentials, config=tmp_path, gid=0)
    policy_path = tmp_path / "gateways.json"
    secret_path = tmp_path / "gateway-credentials"
    assert stat.S_IMODE(policy_path.stat().st_mode) == 0o640
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert secret_path.stat().st_uid == 0
    assert "disposable-fixture-credential" not in policy_path.read_text()
    assert load(tmp_path) == (policy, credentials)


@pytest.mark.parametrize("attack", ["writable-directory", "symlink-directory", "symlink-policy", "symlink-secret", "writable-policy", "foreign-secret"])
def test_unsafe_authority_files_are_refused_without_overwriting_them(tmp_path, attack):
    assert os.geteuid() == 0
    config = tmp_path / "configuration"
    config.mkdir(mode=0o700)
    policy = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}], "bindings": []}
    credentials = {"connectors": {"first": {"token": "disposable-fixture-credential"}}}
    persist(policy, credentials, config=config, gid=0)
    if attack == "writable-directory":
        config.chmod(0o777)
    elif attack == "symlink-directory":
        link = tmp_path / "symlink-config"
        link.symlink_to(config)
        config = link
    elif attack.startswith("symlink-"):
        path = config / ("gateways.json" if attack == "symlink-policy" else "gateway-credentials")
        target = config / "unchanged-neighbor"
        path.rename(target)
        path.symlink_to(target)
    elif attack == "writable-policy":
        (config / "gateways.json").chmod(0o666)
    else:
        os.chown(config / "gateway-credentials", 65534, 65534)
    before = (config / "gateway-credentials").read_bytes()
    with pytest.raises(PermissionError):
        persist(policy, copy.deepcopy(credentials), config=config, gid=0)
    assert (config / "gateway-credentials").read_bytes() == before
