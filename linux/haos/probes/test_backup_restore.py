"""Real encrypted repository and deleted-project restore on disposable fixtures."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.backup import Repository


def test_deleted_project_restores_from_real_restic(tmp_path):
    assert os.geteuid() == 0, "run this isolated fixture probe as root"
    (tmp_path / "owner").mkdir(mode=0o700)
    repository = Repository(tmp_path / "owner", tmp_path / "password")
    repository.initialize()
    source = tmp_path / "workspace"
    source.mkdir()
    project = source / "project.txt"
    payload = b"HAOS disposable lost-project fixture\n" + os.urandom(4096)
    project.write_bytes(payload)
    project.chmod(0o600)
    canary = tmp_path / "unapproved-volume-canary"
    canary.write_text("untouched fixture")
    snapshot = repository.create([source])["snapshot_id"]
    project.unlink()
    result = repository.restore(snapshot)
    restored = Path(result["staging_directory"]) / source.relative_to("/") / "project.txt"
    assert restored.read_bytes() == payload
    assert restored.stat().st_mode & 0o777 == 0o600
    assert not project.exists() and result["live_state_replaced"] is False
    assert canary.read_text() == "untouched fixture"
    repository.password.write_text("incorrect disposable password")
    with pytest.raises(RuntimeError):
        repository.command("snapshots")
    print(json.dumps({"encrypted_repository_wrong_key_denied": True, "deleted_project_restored": True,
                      "live_state_untouched": True, "restored_sha256": hashlib.sha256(payload).hexdigest()}))
