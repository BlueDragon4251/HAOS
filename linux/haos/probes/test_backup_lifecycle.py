"""Real encrypted retention and damaged state recovery in disposable directories."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.backup import Repository, Retention
from haos.store import MissionStore


def repository_at(tmp_path):
    assert os.geteuid() == 0, "run this isolated encrypted-repository fixture as root"
    repository = Repository(tmp_path / "owner", tmp_path / "password")
    repository.initialize()
    return repository


def test_real_retention_preview_scope_and_prune(tmp_path):
    repository = repository_at(tmp_path)
    source = tmp_path / "workspace"
    source.mkdir()
    file = source / "retained.txt"
    file.write_text("earlier disposable revision")
    first = repository.create([source])["snapshot_id"]
    file.write_text("current disposable revision")
    latest = repository.create([source])["snapshot_id"]
    # Another caller's snapshots and a different source group must survive.
    foreign = repository.command("backup", "--tag", "other-owner-fixture", str(source))
    foreign_id = next(json.loads(line)["snapshot_id"] for line in foreign.splitlines()
                      if json.loads(line).get("message_type") == "summary")
    another = tmp_path / "second-scope"
    another.mkdir()
    (another / "other.txt").write_text("separate scope")
    other = repository.create([another])["snapshot_id"]
    policy = Retention(1, 0, 0, 0)
    preview = repository.retain(policy)
    assert preview["dry_run"]
    assert preview["selected_for_removal"] == [first]
    assert set(repository.snapshots()["snapshot_ids"]) == {first, latest, other}
    applied = repository.retain(policy, apply=True)
    assert not applied["dry_run"] and applied["selected_for_removal"] == [first]
    assert set(repository.snapshots()["snapshot_ids"]) == {latest, other}
    actual = json.loads(repository.command("snapshots"))
    assert foreign_id in {row["id"] for row in actual}
    staged = Path(repository.restore(latest)["staging_directory"])
    assert (staged / source.relative_to("/") / file.name).read_text() == "current disposable revision"
    print(json.dumps({"actual_encrypted_retention": True, "preview_did_not_delete": True,
                      "other_tag_and_source_group_preserved": True, "retained_snapshot_restored": True}))


def test_damaged_configuration_and_mission_database_restore_into_staging(tmp_path):
    repository = repository_at(tmp_path)
    source = tmp_path / "isolated-system-state"
    source.mkdir()
    control = source / "control"
    control.mkdir()
    db = control / "missions.db"
    store = MissionStore(db)
    mission = store.create("fixture-owner", "durable-request", "Restore this disposable state")
    store.request_cancel(mission["id"], "fixture-owner")
    expected = store.get(mission["id"])
    events = store.events(mission["id"])
    store.close()
    config = source / "config"
    config.mkdir()
    policy = {"version": 1, "volumes": [{"id": "UUID:disposable-data", "mode": "blocked"}]}
    (config / "volumes.json").write_text(json.dumps(policy))
    (config / "volumes.json").chmod(0o600)
    theme = source / "themes"
    theme.mkdir()
    (theme / "manifest.json").write_text(json.dumps({"fixture": "saved-version"}))
    (theme / "wallpaper.png").write_bytes(b"opaque saved fixture asset")
    canary = tmp_path / "unapproved-neighbor"
    canary.write_text("never changed")
    snapshot = repository.create([source])["snapshot_id"]
    # Destroy/replace only this test's state, not the running OS or any real disk.
    shutil.rmtree(source)
    source.mkdir()
    (source / "broken-config").write_text("damaged replacement")
    result = repository.restore(snapshot)
    staged = Path(result["staging_directory"]) / source.relative_to("/")
    connection = sqlite3.connect(f"file:{staged / 'control/missions.db'}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    restored = MissionStore(staged / "control/missions.db")
    try:
        assert restored.get(mission["id"]) == expected
        assert restored.events(mission["id"]) == events
        assert restored.claim() is None
    finally:
        restored.close()
    assert json.loads((staged / "config/volumes.json").read_text()) == policy
    assert (staged / "config/volumes.json").stat().st_mode & 0o777 == 0o600
    assert (staged / "themes/wallpaper.png").read_bytes() == b"opaque saved fixture asset"
    assert canary.read_text() == "never changed"
    assert (source / "broken-config").read_text() == "damaged replacement"
    assert not result["live_state_replaced"]
    print(json.dumps({"damaged_state_restored_to_staging": True, "actual_sqlite_integrity": True,
                      "mission_identity_events_and_cancellation_preserved": True,
                      "configuration_theme_asset_and_mode_preserved": True, "live_state_untouched": True,
                      "whole_system_recovery_acceptance": False}))


def test_corrupt_encrypted_pack_blocks_restore_and_deletion(tmp_path):
    repository = repository_at(tmp_path)
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "data.bin").write_bytes(os.urandom(8192))
    snapshot = repository.create([source])["snapshot_id"]
    pack = next(path for path in (repository.repository / "data").rglob("*") if path.is_file())
    data = bytearray(pack.read_bytes())
    data[len(data) // 2] ^= 1
    pack.write_bytes(data)
    with pytest.raises(RuntimeError, match="no successful backup/restore receipt"):
        repository.restore(snapshot)
    with pytest.raises(RuntimeError, match="no successful backup/restore receipt"):
        repository.retain(Retention(1, 0, 0, 0), apply=True)
    assert snapshot in repository.snapshots()["snapshot_ids"]
    assert not (repository.root / "restores").exists()
    print(json.dumps({"corrupt_encrypted_data_denied": True, "restore_and_retention_failed_closed": True}))
