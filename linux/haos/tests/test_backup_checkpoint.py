import pytest

from haos.backup_checkpoint import MissionCheckpoint


def test_non_owner_cannot_checkpoint_private_missions(monkeypatch, tmp_path):
    monkeypatch.setattr('haos.backup_checkpoint.os.geteuid', lambda: 1001)
    with pytest.raises(PermissionError):
        MissionCheckpoint(tmp_path / 'owner-state', tmp_path / 'private-ledger', 4252)
    assert not (tmp_path / 'owner-state').exists()
