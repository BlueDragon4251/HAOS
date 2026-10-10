"""Actual kernel ACL operations on disposable root-owned file trees; no disks."""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.volume_acl import (ACCESS, DEFAULT, GROUP_OBJ, MASK, OTHER, UNDEFINED, USER,
                            USER_OBJ, Journal, decode, encode)
from haos.credentials import private_credential

AGENT, FOREIGN, MASKED = 65534, 65533, 65532


@pytest.fixture
def fixture():
    assert os.geteuid() == 0, "root-only, disposable kernel ACL probe"
    parent = Path(tempfile.mkdtemp(prefix="haos-acl-test-", dir="/run"))
    workspace = Path(tempfile.mkdtemp(prefix="haos-acl-data-"))
    workspace.chmod(0o755)
    data = workspace / "data"
    data.mkdir(mode=0o700)
    journal = Journal(parent / "fixture.db", "UUID:disposable", AGENT)
    try:
        yield data, journal, parent
    finally:
        journal.close()
        shutil.rmtree(workspace)
        shutil.rmtree(parent)


def as_uid(uid, code, *arguments):
    result = subprocess.run(["/usr/bin/setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups",
                             "/usr/bin/python3", "-I", "-c", code, *map(str, arguments)],
                            capture_output=True, text=True, timeout=10)
    return result


def test_foreign_owner_write_rename_delete_and_exact_revoke(fixture):
    data, journal, _ = fixture
    os.chown(data, FOREIGN, FOREIGN)
    directory = data / "private"
    directory.mkdir(mode=0o1700)
    original = directory / "original"
    original.write_text("original")
    original.chmod(0o600)
    os.chown(original, FOREIGN, FOREIGN)
    os.chown(directory, FOREIGN, FOREIGN)
    before = (original.stat().st_uid, original.stat().st_gid, stat.S_IMODE(original.stat().st_mode))
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).read_text()", original).returncode != 0
    assert journal.grant(data) == 3
    code = """
import sys
from pathlib import Path
directory = Path(sys.argv[1]); original = directory / 'original'
assert original.read_text() == 'original'
original.write_text('changed'); original.rename(directory / 'renamed')
(directory / 'new').write_text('new')
(directory / 'new').unlink()
"""
    result = as_uid(AGENT, code, directory)
    assert result.returncode == 0, result.stderr
    renamed = directory / "renamed"
    assert renamed.stat().st_uid == FOREIGN and renamed.stat().st_gid == FOREIGN
    # Recovery uses generation-aware handles, not stale names.
    journal.restore(data)
    assert (renamed.stat().st_uid, renamed.stat().st_gid, stat.S_IMODE(renamed.stat().st_mode)) == before
    with pytest.raises(OSError):
        os.getxattr(directory, DEFAULT)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o1700
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).read_text()", renamed).returncode != 0
    assert as_uid(FOREIGN, "import sys;from pathlib import Path;assert Path(sys.argv[1]).read_text()=='changed'", renamed).returncode == 0


def test_mask_expansion_preserves_effective_rights_of_other_users(fixture):
    data, journal, _ = fixture
    data.chmod(0o755)
    file = data / "masked"
    file.write_text("private")
    acl = encode([(USER_OBJ, 6, UNDEFINED), (USER, 7, MASKED), (GROUP_OBJ, 7, UNDEFINED),
                  (MASK, 0, UNDEFINED), (OTHER, 0, UNDEFINED)])
    os.setxattr(file, ACCESS, acl)
    assert as_uid(MASKED, "import sys;from pathlib import Path;Path(sys.argv[1]).read_text()", file).returncode != 0
    journal.grant(data)
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).write_text('approved')", file).returncode == 0
    assert as_uid(MASKED, "import sys;from pathlib import Path;Path(sys.argv[1]).read_text()", file).returncode != 0
    journal.restore(data)
    assert os.getxattr(file, ACCESS) == acl


def test_symlink_target_is_untouched_and_special_file_fails_closed(fixture):
    data, journal, _ = fixture
    outside = data.parent / "protected"
    outside.write_text("protected")
    outside.chmod(0o600)
    (data / "escape").symlink_to(outside)
    before = outside.stat()
    journal.grant(data)
    assert outside.stat().st_mode == before.st_mode
    with pytest.raises(OSError):
        os.getxattr(outside, ACCESS)
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).read_text()", data / "escape").returncode != 0
    os.mkfifo(data / "pipe", 0o600)
    with pytest.raises(PermissionError, match="special files"):
        journal.grant(data)
    journal.restore(data)


def test_inherited_private_grant_new_entries_and_deleted_inode_replacement(fixture):
    data, journal, _ = fixture
    original = data / "replaced"
    original.write_text("old")
    original.chmod(0o640)
    journal.grant(data)
    original.unlink()
    original.write_text("replacement")
    original.chmod(0o600)
    # A foreign creator receives the delegated default ACL; the agent can edit.
    os.chown(original, FOREIGN, FOREIGN)
    result = as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).write_text('new')", original)
    # chmod(0600) intentionally withdrew the ACL mask: full access must be
    # revalidated by a stopped-runtime refresh rather than overriding chmod live.
    assert result.returncode != 0
    journal.grant(data)
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).write_text('new')", original).returncode == 0
    journal.restore(data)
    assert stat.S_IMODE(original.stat().st_mode) == 0o600, "old deleted inode rights were applied to its replacement"
    assert original.stat().st_uid == FOREIGN


def test_read_delegation_never_grants_write(fixture):
    data, journal, _ = fixture
    file = data / "foreign"
    file.write_text("readable")
    file.chmod(0o600)
    os.chown(file, FOREIGN, FOREIGN)
    journal.grant(data, writable=False)
    result = as_uid(AGENT, "import sys;from pathlib import Path;p=Path(sys.argv[1]);assert p.read_text()=='readable';p.write_text('forbidden')", file)
    assert result.returncode != 0 and "PermissionError" in result.stderr
    with pytest.raises(OSError):
        os.getxattr(data, DEFAULT)
    journal.restore(data)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_systemd_style_credential_acl_is_readable_only_by_its_service_uid(fixture):
    data, _, _ = fixture
    data.chmod(0o755)
    file = data / "scoped-credential"
    file.write_text("disposable-scoped-fixture")
    os.setxattr(file, ACCESS, encode([(USER_OBJ, 4, UNDEFINED), (USER, 4, AGENT),
                                   (GROUP_OBJ, 0, UNDEFINED), (MASK, 4, UNDEFINED), (OTHER, 0, UNDEFINED)]))
    assert stat.S_IMODE(file.stat().st_mode) == 0o440
    for uid, expected in ((AGENT, 0), (FOREIGN, 1)):
        pid = os.fork()
        if pid == 0:
            try:
                os.setgroups([])
                os.setgid(uid)
                os.setuid(uid)
                try:
                    assert private_credential(file) == "disposable-scoped-fixture"
                except PermissionError:
                    os._exit(1)
                os._exit(0)
            except BaseException:
                os._exit(3)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == expected


@pytest.mark.parametrize("leak", ["group", "other-user", "write"])
def test_credential_acl_cannot_grant_other_principals_or_service_write(fixture, leak):
    data, _, _ = fixture
    data.chmod(0o755)
    file = data / "credential"
    file.write_text("disposable-fixture")
    entries = [(USER_OBJ, 4, UNDEFINED), (USER, 6 if leak == "write" else 4, AGENT),
               (GROUP_OBJ, 4 if leak == "group" else 0, UNDEFINED),
               (MASK, 6 if leak == "write" else 4, UNDEFINED), (OTHER, 0, UNDEFINED)]
    if leak == "other-user":
        entries.append((USER, 4, FOREIGN))
    os.setxattr(file, ACCESS, encode(entries))
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(AGENT)
            os.setuid(AGENT)
            try:
                private_credential(file)
            except PermissionError:
                os._exit(0)
            os._exit(2)
        except BaseException:
            os._exit(3)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0


def test_journal_is_private_durable_and_wrong_authority_is_rejected(fixture):
    data, journal, parent = fixture
    file = data / "file"
    file.write_text("original")
    file.chmod(0o600)
    journal.grant(data)
    assert as_uid(AGENT, "import sys;from pathlib import Path;Path(sys.argv[1]).read_bytes()", journal.path).returncode != 0
    journal.close()
    with pytest.raises(PermissionError, match="identity differs"):
        Journal(parent / "fixture.db", "UUID:other", AGENT)
    restored = Journal(parent / "fixture.db", "UUID:disposable", AGENT)
    try:
        restored.restore(data)
        assert stat.S_IMODE(data.stat().st_mode) == 0o700
    finally:
        restored.close()


def test_nested_mount_is_excluded_and_rollback_recovers_after_unmount(fixture):
    data, journal, _ = fixture
    assert os.environ.get("HAOS_ACL_DISK_FIXTURE"), "nested-mount test requires the guarded file-backed CI runner"
    nested = data / "nested"
    nested.mkdir()
    subprocess.run(["/usr/bin/mount", "--types", "tmpfs", "--options", "nodev,nosuid,noexec", "tmpfs", str(nested)], check=True)
    try:
        file = nested / "protected"
        file.write_text("protected")
        file.chmod(0o600)
        before = file.stat().st_mode
        with pytest.raises(PermissionError, match="nested mounts"):
            journal.grant(data)
        assert file.stat().st_mode == before
    finally:
        subprocess.run(["/usr/bin/umount", str(nested)], check=True)
    journal.restore(data)
    assert stat.S_IMODE(data.stat().st_mode) == 0o700


@pytest.mark.parametrize("attack", ["symlink", "public", "hardlink"])
def test_journal_authority_cannot_be_substituted(fixture, attack):
    _, journal, parent = fixture
    journal.close()
    path = parent / "fixture.db"
    if attack == "symlink":
        path.rename(parent / "real")
        path.symlink_to(parent / "real")
    elif attack == "public":
        path.chmod(0o644)
    else:
        os.link(path, parent / "alias")
    with pytest.raises((PermissionError, OSError)):
        Journal(path, "UUID:disposable", AGENT)
