"""Real private hashes, replay prevention and serialized recovery in disposable /run fixtures."""

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.owner_recovery import RecoveryCodes


@pytest.fixture
def location():
    assert os.geteuid() == 0, "run this explicit authority probe as root"
    directory = Path(tempfile.mkdtemp(prefix="haos-recovery-probe-", dir="/run"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def store(location):
    return RecoveryCodes(location / "recovery.json", location / "recovery.lock")


def test_codes_are_private_non_plaintext_single_use_and_survive_reopen(location):
    codes = store(location).issue(1500)
    assert len(codes) == len(set(codes)) == 10
    path = location / "recovery.json"
    assert path.stat().st_mode & 0o777 == 0o600 and path.stat().st_uid == 0
    assert all(code not in path.read_text() for code in codes)
    reopened = store(location)
    reopened.consume(1500, codes[0])
    with pytest.raises(PermissionError):
        store(location).consume(1500, codes[0])
    assert len(json.loads(path.read_text())["owners"]["1500"]["hashes"]) == 9
    with pytest.raises(PermissionError):
        store(location).consume(1501, codes[1])


def test_wrong_code_backoff_and_regeneration_revocation_are_persistent(location):
    codes = store(location).issue(1500)
    with pytest.raises(PermissionError):
        store(location).consume(1500, "incorrect-code", now=100)
    with pytest.raises(PermissionError):
        store(location).consume(1500, codes[0], now=101)
    store(location).consume(1500, codes[0], now=103)
    fresh = store(location).issue(1500)
    with pytest.raises(PermissionError):
        store(location).consume(1500, codes[1], now=104)
    store(location).consume(1500, fresh[0], now=110)


def test_concurrent_recovery_cannot_consume_the_same_code_twice(location):
    code = store(location).issue(1500)[0]
    def consume(_):
        try:
            store(location).consume(1500, code)
            return True
        except PermissionError:
            return False
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]


@pytest.mark.parametrize("kind", ["symlink", "public", "foreign", "corrupt"])
def test_unsafe_or_corrupt_recovery_authority_never_authenticates(location, kind):
    code = store(location).issue(1500)[0]
    path = location / "recovery.json"
    if kind == "symlink":
        path.rename(location / "neighbor")
        path.symlink_to(location / "neighbor")
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "foreign":
        os.chown(path, 65534, 65534)
    else:
        data = json.loads(path.read_text())
        data["owners"]["1500"]["hashes"] = ["bad-hash"]
        path.write_text(json.dumps(data))
    with pytest.raises(PermissionError):
        store(location).consume(1500, code)
