"""Enrollment validation and interrupted provisioning must fail closed."""

from pathlib import Path
from types import SimpleNamespace
import os
import stat
import subprocess

import pytest

from haos import enrollment as e


def root_file_identity(monkeypatch, tmp_path, uid=0):
    # Unit fixtures simulate ownership; the disposable root probe checks real UIDs.
    original = os.fstat
    def metadata(fd):
        real = original(fd)
        lock = e.LOCK
        if lock.is_relative_to(tmp_path) and lock.exists():
            info = lock.stat()
            if (real.st_dev, real.st_ino) == (info.st_dev, info.st_ino):
                fields = list(real)
                fields[4] = uid
                return os.stat_result(fields)
        return real
    def chown(fd, owner, group):
        assert stat.S_ISREG(original(fd).st_mode)
        assert (owner, group) == (0, 0)
    monkeypatch.setattr(e.os, "fstat", metadata)
    monkeypatch.setattr(e.os, "fchown", chown)


@pytest.mark.parametrize("name", ["root", "hermes", "haos-agent", "haos-control", "haos-gateway", "haos-provider", "observer", "a;id", "-a", "A", "a" * 32])
def test_reject_unsafe_or_reserved_identity(name):
    with pytest.raises((PermissionError, ValueError)):
        e.validate_name(name, "observer")


def test_existing_account_never_repurposed(monkeypatch):
    monkeypatch.setattr(e.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1200))
    with pytest.raises(PermissionError, match="new account"):
        e.validate_name("owner", "observer")


@pytest.mark.parametrize("password", ["short", "a" * 257, "abcdefghijklmnopqrst\n", "abcdefghijklmnopqrst\x00", "the-owner-password-is-too-obvious"])
def test_bad_password_rejected_before_any_command(monkeypatch, password):
    monkeypatch.setattr(e, "run", lambda *a, **k: pytest.fail("unsafe input reached password command"))
    with pytest.raises(ValueError):
        e.password_quality("owner", password)


def test_password_sent_only_to_stdin_and_quality_required(monkeypatch):
    seen = []
    def check(*args, **kwargs):
        seen.append((args, kwargs))
        return "85\n"
    monkeypatch.setattr(e, "run", check)
    password = "Ci-fixture-unique!46-question"
    e.password_quality("owner", password)
    assert seen == [(("/usr/bin/pwscore", "owner"), {"secret": password + "\n"})]
    monkeypatch.setattr(e, "run", lambda *a, **k: "unverified")
    with pytest.raises(PermissionError):
        e.password_quality("owner", password)


def test_subprocess_failures_do_not_expose_password_or_output(monkeypatch):
    monkeypatch.setattr(e.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="password fixture", stderr="password fixture"))
    with pytest.raises(RuntimeError) as error:
        e.run("/usr/sbin/chpasswd", secret="password fixture")
    assert "password fixture" not in str(error.value)


def test_only_fixed_cli_requires_new_password_authentication():
    rule = e.sudo_rule(1500)
    assert "timestamp_timeout=0" in rule and "!setenv" in rule and "env_reset" in rule
    assert "#1500 ALL=(ALL:ALL) !ALL" in rule
    assert "#1500 ALL=(root:root) PASSWD: NOSETENV: /usr/bin/haos-owner" in rule
    assert "NOPASSWD" not in rule
    with pytest.raises(PermissionError):
        e.sudo_rule(True)


@pytest.mark.parametrize("shared,groups", [(True, []), (False, [SimpleNamespace(gr_name="wheel", gr_gid=1500, gr_mem=[])]),
                                         (False, [SimpleNamespace(gr_name="haos-ui", gr_gid=2000, gr_mem=["owner"])])])
def test_account_rejects_aliases_and_authority_groups(monkeypatch, shared, groups):
    entry = SimpleNamespace(pw_name="owner", pw_uid=1500, pw_gid=1500)
    alias = SimpleNamespace(pw_name="alias", pw_uid=1500, pw_gid=1500)
    monkeypatch.setattr(e.pwd, "getpwnam", lambda _: entry)
    monkeypatch.setattr(e.pwd, "getpwall", lambda: [entry, alias] if shared else [entry])
    monkeypatch.setattr(e.grp, "getgrall", lambda: groups)
    with pytest.raises(PermissionError):
        e.verify_account("owner")


def test_full_sudoers_validation_failure_removes_published_grant(monkeypatch, tmp_path):
    root_file_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(e, "protected_directory", lambda _: None)
    def validate(*args, **kwargs):
        if len(args) == 2:
            raise RuntimeError("invalid full sudo policy")
        return ""
    monkeypatch.setattr(e, "run", validate)
    with pytest.raises(RuntimeError):
        e.install_rule(1500, tmp_path)
    assert not list(tmp_path.iterdir())


def provisioning_fixture(monkeypatch, tmp_path, fail_at=None):
    root_file_identity(monkeypatch, tmp_path)
    entry = SimpleNamespace(pw_name="owner", pw_uid=1500, pw_gid=1500)
    accounts = {}
    calls = []
    rule = tmp_path / "sudo-rule"
    def lookup(user):
        if user not in accounts:
            raise KeyError(user)
        return accounts[user]
    def command(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0].endswith("useradd"):
            accounts["owner"] = entry
        if fail_at and args[0].endswith(fail_at):
            raise RuntimeError("fixture interruption")
        if args[0].endswith("passwd"):
            state = "P" if any(a[0].endswith("chpasswd") for a, k in calls) else "L"
            return f"owner {state} 2026-10-09 0 99999 7 -1\n"
        return ""
    def install(uid):
        rule.write_text(e.sudo_rule(uid))
        return rule
    monkeypatch.setattr(e.os, "geteuid", lambda: 0)
    monkeypatch.setattr(e, "trusted_json", lambda p: {"control_users": ["observer"]})
    monkeypatch.setattr(e, "protected_directory", lambda _: None)
    monkeypatch.setattr(e, "password_quality", lambda *a: None)
    monkeypatch.setattr(e, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(e, "REGISTRY", tmp_path / "registry" / "owners.json")
    monkeypatch.setattr(e, "run", command)
    monkeypatch.setattr(e, "install_rule", install)
    monkeypatch.setattr(e.pwd, "getpwnam", lookup)
    monkeypatch.setattr(e, "verify_account", lambda *a: entry)
    monkeypatch.setattr("haos.owner.audit", lambda *a: None)
    return calls, rule


@pytest.mark.parametrize("fail_at", ["useradd", "chpasswd"])
def test_interrupted_provisioning_revokes_grant_and_locks_new_account(monkeypatch, tmp_path, fail_at):
    calls, rule = provisioning_fixture(monkeypatch, tmp_path, fail_at)
    with pytest.raises(RuntimeError):
        e.enroll("owner", "fixture-password")
    assert not rule.exists()
    assert ("/usr/sbin/usermod", "--lock", "owner") in [a for a, k in calls]
    assert not e.REGISTRY.exists()


def test_success_records_identity_without_secret(monkeypatch, tmp_path):
    calls, rule = provisioning_fixture(monkeypatch, tmp_path)
    result = e.enroll("owner", "fixture-password")
    assert result["uid"] == 1500 and rule.exists()
    assert "fixture-password" not in e.REGISTRY.read_text()
    assert not any(a[0].endswith("usermod") for a, k in calls)


def test_initial_onboarding_cannot_reopen_after_another_owner_won_the_lock(monkeypatch, tmp_path):
    calls, rule = provisioning_fixture(monkeypatch, tmp_path)
    e.REGISTRY.parent.mkdir()
    e.REGISTRY.write_text('{"schema_version": 1, "owners": [{"username": "previous-owner", "uid": 1501}]}')
    def configuration(path):
        import json
        return json.loads(path.read_text()) if path == e.REGISTRY else {"control_users": ["observer"]}
    monkeypatch.setattr(e, "trusted_json", configuration)
    with pytest.raises(PermissionError, match="already completed"):
        e.enroll("owner", "fixture-password", initial_only=True)
    assert calls == [] and not rule.exists()


def test_failed_audit_rolls_back_registry_and_locks_account(monkeypatch, tmp_path):
    calls, rule = provisioning_fixture(monkeypatch, tmp_path)
    def fail(*args):
        raise OSError("audit unavailable")
    monkeypatch.setattr("haos.owner.audit", fail)
    with pytest.raises(OSError):
        e.enroll("owner", "fixture-password")
    assert not rule.exists() and '"owners": []' in e.REGISTRY.read_text()
    assert ("/usr/sbin/usermod", "--lock", "owner") in [a for a, k in calls]


@pytest.mark.parametrize("kind", ["foreign-owner", "readable", "symlink"])
def test_untrusted_enrollment_lock_never_provisions(monkeypatch, tmp_path, kind):
    calls, rule = provisioning_fixture(monkeypatch, tmp_path)
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("untouched")
        e.LOCK.symlink_to(target)
    else:
        e.LOCK.write_text("")
        e.LOCK.chmod(0o640 if kind == "readable" else 0o600)
        if kind == "foreign-owner":
            root_file_identity(monkeypatch, tmp_path, uid=1001)
    with pytest.raises((PermissionError, OSError)):
        e.enroll("owner", "fixture-password")
    assert not calls and not rule.exists() and not e.REGISTRY.exists()
    if kind == "symlink":
        assert target.read_text() == "untouched"


def test_nonroot_and_noninteractive_enrollment_rejected(monkeypatch):
    monkeypatch.setattr(e.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        e.enroll("owner", "fixture-password")
    monkeypatch.setattr(e.sys.stdin, "isatty", lambda: False)
    with pytest.raises(PermissionError, match="interactive"):
        e.enroll_interactive("owner")


def test_owner_launcher_ignores_attacker_python_startup_and_package(tmp_path):
    source = Path(__file__).parents[2] / "bin" / "haos-owner"
    launcher = tmp_path / "haos-owner"
    launcher.write_bytes(source.read_bytes())
    launcher.chmod(0o755)  # Match install.sh rather than the source file mode.
    marker = tmp_path / "executed"
    malicious = f"from pathlib import Path; Path({str(marker)!r}).write_text('attacker')\n"
    (tmp_path / "sitecustomize.py").write_text(malicious)
    package = tmp_path / "haos"
    package.mkdir()
    (package / "__init__.py").write_text(malicious)
    (package / "owner.py").write_text("def main(): pass\n")
    result = subprocess.run([str(launcher), "--help"], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(tmp_path)}, capture_output=True, text=True)
    assert not marker.exists()
    # A development machine need not have /usr/lib/haos installed. Missing
    # immutable code must fail instead of loading the caller's fake package.
    if result.returncode:
        assert "ModuleNotFoundError" in result.stderr
