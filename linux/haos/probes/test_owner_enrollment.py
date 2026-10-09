"""Real PAM/password/sudo checks; only on an explicitly disposable CI runner."""

import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.enrollment import enroll
from haos.observer import ENV


def run(*args, secret=None, check=True):
    return subprocess.run(list(args), input=secret, env=ENV, capture_output=True, text=True, check=check, timeout=30)


def test_password_authenticated_owner_has_only_fixed_cli(tmp_path):
    assert os.geteuid() == 0
    assert os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HAOS_DISPOSABLE_CI") == "1"
    config, installed, launcher = Path("/etc/haos"), Path("/usr/lib/haos"), Path("/usr/bin/haos-owner")
    registry = Path("/var/lib/haos-owner")
    assert all(not p.exists() and not p.is_symlink() for p in (config, installed, launcher, registry))
    user = "haos-owner-" + uuid.uuid4().hex[:10]
    password = secrets.token_urlsafe(28) + "!Aa42"
    try:
        config.mkdir(mode=0o700)
        (config / "controller.json").write_text(json.dumps({"control_users": ["haos-observer-fixture"]}))
        (config / "volumes.json").write_text(json.dumps({"fixture": user, "volumes": []}))
        for p in config.iterdir():
            p.chmod(0o600)
        shutil.copytree(Path(__file__).parents[1] / "haos", installed / "haos")
        shutil.copy2(Path(__file__).parents[2] / "bin" / "haos-owner", launcher)
        launcher.chmod(0o755)
        receipt = enroll(user, password)
        prefix = ("/usr/sbin/runuser", "-u", user, "--", "/usr/bin/sudo")
        denied = run(*prefix, "-n", str(launcher), "status", check=False)
        assert denied.returncode != 0
        wrong = run(*prefix, "-S", "-k", str(launcher), "status", secret="wrong-ci-password\n", check=False)
        assert wrong.returncode != 0
        allowed = run(*prefix, "-S", "-k", str(launcher), "status", secret=password + "\n")
        assert json.loads(allowed.stdout)["policy"]["fixture"] == user
        # An authenticated call must not create a reusable sudo timestamp.
        assert run(*prefix, "-n", str(launcher), "status", check=False).returncode != 0
        arbitrary = run(*prefix, "-S", "-k", "/usr/bin/id", "-u", secret=password + "\n", check=False)
        assert arbitrary.returncode != 0 and arbitrary.stdout.strip() != "0"
        environment = run(*prefix, "-S", "-k", "PYTHONPATH=/tmp", str(launcher), "status",
                          secret=password + "\n", check=False)
        assert environment.returncode != 0
        assert password not in (registry / "owners.json").read_text()
        assert password not in (registry / "audit.jsonl").read_text()
        run("/usr/sbin/visudo", "-c")
        print(json.dumps({"password_authenticated_fixed_cli": True, "wrong_password_denied": True,
                          "cached_authentication_denied": True, "arbitrary_root_command_denied": True,
                          "python_environment_override_denied": True, "secret_absent_from_registry_and_audit": True}))
    finally:
        # Include enrollment failures after useradd; no real pre-existing user
        # or directory is ever removed by this uniquely named fixture.
        try:
            entry = pwd.getpwnam(user)
        except KeyError:
            pass
        else:
            (Path("/etc/sudoers.d") / f"zzzz-haos-owner-{entry.pw_uid}").unlink(missing_ok=True)
            run("/usr/sbin/userdel", "--remove", user, check=False)
        launcher.unlink(missing_ok=True)
        for p in (config, installed, registry):
            if p.exists():
                shutil.rmtree(p)
        Path("/run/haos-owner-enroll.lock").unlink(missing_ok=True)
