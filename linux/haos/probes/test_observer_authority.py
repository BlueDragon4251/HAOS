"""Actual sudo/group/password checks on a newly created disposable CI account."""

import grp
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.observer import secure_observer


def run(*args, check=True):
    return subprocess.run(list(args), check=check, capture_output=True, text=True)


def test_inherited_sudo_and_blank_password_are_denied():
    assert os.geteuid() == 0, "run only on the disposable CI runner as root"
    user = "haos-fixture-" + uuid.uuid4().hex[:10]
    grant = Path("/etc/sudoers.d") / ("00-" + user)
    deny = Path("/etc/sudoers.d") / ("zzzz-" + user)
    assert not grant.exists() and not deny.exists()
    created = False
    try:
        grp.getgrnam("sudo")
        run("/usr/sbin/useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", "--groups", "sudo", user)
        created = True
        run("/usr/bin/passwd", "--delete", user)
        grant.write_text(f"{user} ALL=(ALL:ALL) NOPASSWD: ALL\n")
        grant.chmod(0o440)
        run("/usr/sbin/visudo", "-c")
        # Demonstrate actual inherited privilege before testing its removal.
        before = run("/usr/sbin/runuser", "-u", user, "--", "/usr/bin/sudo", "-n", "/usr/bin/id", "-u")
        assert before.stdout.strip() == "0"
        receipt = secure_observer(user, deny)
        assert user not in grp.getgrnam("sudo").gr_mem
        assert run("/usr/bin/passwd", "--status", user).stdout.split()[1] == "L"
        after = run("/usr/sbin/runuser", "-u", user, "--", "/usr/bin/sudo", "-n", "/usr/bin/id", "-u", check=False)
        assert after.returncode != 0 and after.stdout.strip() != "0"
        edit = run("/usr/sbin/runuser", "-u", user, "--", "/usr/bin/sudo", "-n", "-e", "/etc/haos/volumes.json", check=False)
        assert edit.returncode != 0
        run("/usr/sbin/visudo", "-c")
        print(json.dumps({**receipt, "inherited_nopasswd_denied": True, "sudoedit_denied": True}))
    finally:
        grant.unlink(missing_ok=True)
        deny.unlink(missing_ok=True)
        if created:
            run("/usr/sbin/userdel", user)
