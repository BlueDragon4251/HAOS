import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from haos.backup import Repository, Retention, private_password, owner_backup


@pytest.fixture
def repository(tmp_path):
    password = tmp_path / "password"
    password.write_text("disposable-test-key")
    password.chmod(0o600)
    return Repository(tmp_path / "owner", password)


def test_agent_cannot_enter_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr("haos.backup.os.geteuid", lambda: 1001)
    with pytest.raises(PermissionError):
        Repository(tmp_path / "owner", tmp_path / "password")


def test_backup_requires_fully_stopped_runtime(monkeypatch):
    def denied():
        raise PermissionError("runtime is still running")
    monkeypatch.setattr("haos.owner.stopped", denied)
    with pytest.raises(PermissionError, match="runtime"):
        owner_backup("create")


def test_password_symlink_and_readable_key_denied(repository):
    repository.password.chmod(0o644)
    with pytest.raises(PermissionError):
        private_password(repository.password)
    repository.password.unlink()
    repository.password.symlink_to("/etc/passwd")
    with pytest.raises(PermissionError):
        private_password(repository.password)


def test_inherited_hooks_are_removed_and_partial_backups_fail(repository, monkeypatch):
    def execute(args, **kwargs):
        assert "RESTIC_PASSWORD_COMMAND" not in kwargs["env"]
        assert "--password-file" in args and "disposable-test-key" not in " ".join(args)
        return SimpleNamespace(returncode=3, stdout="", stderr="partial backup")
    monkeypatch.setenv("RESTIC_PASSWORD_COMMAND", "unexpected-owner-hook")
    monkeypatch.setattr("haos.backup.subprocess.run", execute)
    with pytest.raises(RuntimeError, match="exit 3"):
        repository.command("backup")


def test_restore_rejects_ambiguous_or_injected_identifiers(repository):
    for value in ("latest", "abcd", "../root", "a" * 64 + ":/etc"):
        with pytest.raises(ValueError):
            repository.restore(value)


def test_incomplete_restore_is_retained_and_never_reported_success(repository, monkeypatch):
    def execute(*args):
        if args[0] == "restore":
            raise RuntimeError("interrupted restore")
    monkeypatch.setattr(repository, "command", execute)
    with pytest.raises(RuntimeError):
        repository.restore("a" * 64)
    assert list((repository.root / "restores").glob("*/HAOS_RESTORE_INCOMPLETE"))


def test_snapshot_requires_a_complete_receipt(repository, tmp_path, monkeypatch):
    source = tmp_path / "workspace"
    source.mkdir()
    monkeypatch.setattr(repository, "command", lambda *a: json.dumps({"message_type": "summary"}))
    with pytest.raises(ValueError, match="snapshot receipt"):
        repository.create([source])
    with pytest.raises(ValueError, match="overlap"):
        repository.create([tmp_path])


@pytest.mark.parametrize("policy", [Retention(0), Retention(True), Retention(513),
                                    Retention(1, -1), Retention(1, 367), Retention(1, 0, 105),
                                    Retention(1, 0, 0, 121)])
def test_retention_cannot_delete_every_scope_or_accept_invalid_counts(policy):
    with pytest.raises(ValueError, match="retention"):
        policy.arguments()


def test_retention_defaults_to_preview_and_hides_snapshot_metadata(repository, monkeypatch):
    commands = []
    def execute(*args):
        commands.append(args)
        return json.dumps([{"host": "private-test-host", "paths": ["private-file-name"],
                            "keep": [{"id": "a" * 64, "hostname": "private-test-host"}],
                            "remove": [{"id": "b" * 64, "username": "private-owner"}]}])
    monkeypatch.setattr(repository, "command", execute)
    result = repository.retain(Retention(1, 0, 0, 0))
    assert "--dry-run" in commands[-1] and "--prune" not in commands[-1]
    assert commands[0] == ("check", "--read-data")
    assert result["dry_run"] and result["selected_for_removal"] == ["b" * 64]
    assert "private-" not in json.dumps(result)


def test_failed_integrity_check_prevents_any_retention(repository, monkeypatch):
    commands = []
    def execute(*args):
        commands.append(args)
        raise RuntimeError("damaged encrypted data")
    monkeypatch.setattr(repository, "command", execute)
    with pytest.raises(RuntimeError):
        repository.retain(Retention(1, 0, 0, 0), apply=True)
    assert commands == [("check", "--read-data")]


def test_hardlinked_backup_key_is_not_accepted(repository):
    import os
    os.link(repository.password, repository.root / "key-copy")
    with pytest.raises(PermissionError):
        private_password(repository.password)
