from types import SimpleNamespace

import pytest

from haos import observer


@pytest.fixture
def environment(monkeypatch):
    entry = SimpleNamespace(pw_name="observer", pw_uid=1001, pw_gid=1001)
    monkeypatch.setattr(observer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(observer.pwd, "getpwnam", lambda user: entry)
    monkeypatch.setattr(observer.pwd, "getpwall", lambda: [entry])
    monkeypatch.setattr(observer.grp, "getgrall", lambda: [])
    calls = []
    statuses = ["observer L"]
    def command(*args):
        calls.append(args)
        output = statuses.pop(0) if args[:2] == ("/usr/bin/passwd", "--status") else ""
        return SimpleNamespace(stdout=output)
    monkeypatch.setattr(observer, "command", command)
    monkeypatch.setattr(observer, "deny_sudo", lambda uid, path: calls.append(("deny_sudo", uid)))
    return entry, calls, statuses


def test_empty_password_locks_and_inherited_admin_groups_are_removed(environment, monkeypatch):
    entry, calls, statuses = environment
    statuses[:] = ["observer NP", "observer L"]
    groups = [SimpleNamespace(gr_name=name, gr_gid=gid, gr_mem=["observer"])
              for name, gid in [("wheel", 10), ("sudo", 27), ("admin", 80), ("video", 44)]]
    monkeypatch.setattr(observer.grp, "getgrall", lambda: groups)
    assert observer.secure_observer("observer")["sudo_denied"] is True
    assert ("/usr/sbin/usermod", "--lock", "observer") in calls
    assert [row[-1] for row in calls if row[0] == "/usr/bin/gpasswd"] == ["wheel", "sudo", "admin"]
    assert calls[-1] == ("deny_sudo", 1001)


def test_existing_password_is_preserved_without_granting_admin_authority(environment):
    _, calls, statuses = environment
    statuses[:] = ["observer P"]
    observer.secure_observer("observer")
    assert not any(row[0] == "/usr/sbin/usermod" for row in calls)
    assert calls[-1] == ("deny_sudo", 1001)


@pytest.mark.parametrize("uid", [0, 999])
def test_root_alias_and_service_uid_are_rejected_before_commands(environment, uid):
    entry, calls, _ = environment
    entry.pw_uid = uid
    with pytest.raises(PermissionError):
        observer.secure_observer("observer")
    assert not calls


def test_shared_uid_and_administrator_primary_group_fail_closed(environment, monkeypatch):
    entry, calls, _ = environment
    alias = SimpleNamespace(pw_name="owner", pw_uid=entry.pw_uid)
    monkeypatch.setattr(observer.pwd, "getpwall", lambda: [entry, alias])
    with pytest.raises(PermissionError, match="shared"):
        observer.secure_observer("observer")
    monkeypatch.setattr(observer.pwd, "getpwall", lambda: [entry])
    monkeypatch.setattr(observer.grp, "getgrall", lambda: [SimpleNamespace(
        gr_name="wheel", gr_gid=entry.pw_gid, gr_mem=[])])
    with pytest.raises(PermissionError, match="primary"):
        observer.secure_observer("observer")
    assert not calls


@pytest.mark.parametrize("statuses", [["observer NP", "observer NP"], ["owner P"], ["observer unknown"]])
def test_unverified_password_state_does_not_complete_security(environment, statuses):
    _, calls, responses = environment
    responses[:] = statuses
    with pytest.raises(PermissionError):
        observer.secure_observer("observer")
    assert not any(row[0] == "deny_sudo" for row in calls)


def test_unprivileged_or_sudo_syntax_name_cannot_configure_an_account(environment, monkeypatch):
    _, calls, _ = environment
    with pytest.raises(ValueError):
        observer.secure_observer("observer ALL=(ALL) ALL")
    monkeypatch.setattr(observer.os, "geteuid", lambda: 1001)
    with pytest.raises(PermissionError):
        observer.secure_observer("observer")
    assert not calls
