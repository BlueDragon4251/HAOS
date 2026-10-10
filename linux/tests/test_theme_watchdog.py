"""Real independent rollback processes and fixed-output security boundaries."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = ROOT / "linux/bin/herald-os-theme-watchdog"
ENGINE = ROOT / "linux/bin/herald-os-theme"
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.geteuid() == 0,
                              reason="actual unprivileged Linux observer process fixture")


@pytest.fixture
def guard(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    module = runpy.run_path(str(WATCHDOG))
    instance = module["ThemeGuard"]()
    instance.write(instance.prefs, json.dumps({"themeName": "previous", "themeRevision": "a" * 64,
                    "theme": "ocean", "accent": "blue", "favorites": ["retained"],
                    "privateOtherSetting": "not-in-theme-journal"}).encode())
    for key, target in instance.targets.items():
        instance.write(target, ("previous " + key).encode())
    yield instance
    state = instance.load()
    if state and state["status"] == "pending":
        try:
            instance.recover(state["token"])
        except PermissionError:
            pass
    if state and state["watcher"]:
        wait_for(lambda: module["process_identity"](state["watcher"]) is None)


def wait_for(check):
    deadline = time.monotonic() + 5
    while not check():
        if time.monotonic() >= deadline:
            raise AssertionError("real theme watchdog did not finish")
        time.sleep(0.025)


def outputs(guard):
    return {target: "candidate " + key for key, target in guard.targets.items()}


def activate(guard, parent=None):
    targets = outputs(guard)
    token = guard.begin("candidate", "b" * 64, parent or os.getpid(), targets)
    with guard.lock():
        for target, data in targets.items():
            guard.write(target, data.encode())
        prefs = guard.preferences() | {"themeName": "candidate", "themeRevision": "b" * 64,
                                      "theme": "graphite", "accent": "violet"}
        guard.write(guard.prefs, json.dumps(prefs).encode())
    return token


def test_actual_watcher_confirms_only_exact_outputs_and_keeps_private_unrelated_preferences(guard):
    token = activate(guard)
    assert guard.load()["watcher"] != os.getpid()
    assert b"not-in-theme-journal" not in (guard.root / "state.json").read_bytes()
    guard.commit(token)
    assert guard.load()["status"] == "committed"
    assert guard.preferences()["favorites"] == ["retained"]
    assert guard.recover() is False
    assert all(target.read_text() == "candidate " + key for key, target in guard.targets.items())


def test_real_parent_sigkill_rolls_back_partial_files_without_any_controller(guard):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(guard.home), "HERMES_HOME": str(guard.hermes), "LANG": "C.UTF-8"}
    script = """
import json,os,runpy,sys
g=runpy.run_path(sys.argv[1])['ThemeGuard']()
targets={target:'candidate '+key for key,target in g.targets.items()}
token=g.begin('candidate','b'*64,os.getpid(),targets)
with g.lock():
    for target in list(targets)[:3]: g.write(target,targets[target].encode())
    p=g.preferences()|{'themeName':'candidate','themeRevision':'b'*64,'accent':'violet','favorites':['changed during mission']}
    g.write(g.prefs,json.dumps(p).encode())
print(token,flush=True)
sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(WATCHDOG)], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # Bounded read through select; a failed setup must not hang this test.
        import select
        assert select.select([child.stdout], [], [], 5)[0]
        token = child.stdout.readline().strip()
        assert str(uuid.UUID(token)) == token
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=5)
        wait_for(lambda: guard.load()["status"] == "rolled_back")
        assert all(target.read_text() == "previous " + key for key, target in guard.targets.items())
        prefs = guard.preferences()
        assert prefs["themeName"] == "previous" and prefs["accent"] == "blue"
        assert prefs["favorites"] == ["changed during mission"]
        assert prefs["privateOtherSetting"] == "not-in-theme-journal"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize("cause", ["deadline", "different-boot", "different-parent-start"])
def test_actual_independent_watcher_recovers_expiry_and_identity_change(guard, cause):
    activate(guard)
    with guard.lock():
        state = guard.load()
        if cause == "deadline":
            state["deadline_ns"] = 0
        elif cause == "different-boot":
            state["boot"] = str(uuid.uuid4())
        else:
            state["parent_start"] = "0"
        guard.save(state)
    wait_for(lambda: guard.load()["status"] == "rolled_back")
    assert guard.preferences()["themeName"] == "previous"
    assert all(target.read_text() == "previous " + key for key, target in guard.targets.items())


def test_wrong_tokens_and_changed_outputs_cannot_commit_or_restore(guard):
    token = activate(guard)
    with pytest.raises(PermissionError):
        guard.commit(str(uuid.uuid4()))
    with pytest.raises(PermissionError):
        guard.recover(str(uuid.uuid4()))
    target = guard.targets["niri"]
    guard.write(target, b"unrelated manual edit")
    with pytest.raises(PermissionError):
        guard.commit(token)
    with pytest.raises(PermissionError, match="conflict"):
        guard.recover(token)
    assert target.read_bytes() == b"unrelated manual edit"
    assert guard.load()["status"] == "rollback_conflict"
    with pytest.raises(PermissionError):
        guard.begin("candidate", "b" * 64, os.getpid(), outputs(guard))


def test_missing_changed_file_is_preserved_as_conflict(guard):
    token = activate(guard)
    guard.targets["terminal"].unlink()
    with pytest.raises(PermissionError, match="conflict"):
        guard.recover(token)
    assert not guard.targets["terminal"].exists()


def test_restart_command_restores_without_reexecuting_theme_and_normal_set_cannot_trample_pending(guard):
    activate(guard)
    denied = subprocess.run([sys.executable, str(ENGINE), "set", "herald-ocean"], capture_output=True, timeout=5)
    assert denied.returncode != 0 and b"pending theme activation" in denied.stderr
    recovered = subprocess.run([sys.executable, str(ENGINE), "recover"], capture_output=True, timeout=5)
    assert recovered.returncode == 0
    assert guard.load()["status"] == "rolled_back"
    assert guard.preferences()["themeName"] == "previous"


@pytest.mark.parametrize("attack", ["symlink-file", "hardlink-file", "fifo", "writable-file", "symlink-parent", "writable-parent"])
def test_fixed_output_attacks_are_denied_before_candidate_writes(guard, attack):
    target = guard.targets["niri"]
    original = target.read_bytes()
    secret = guard.home / "unrelated-file"
    secret.write_bytes(b"unrelated file must remain unchanged")
    if attack == "symlink-file":
        target.unlink(); target.symlink_to(secret)
    elif attack == "hardlink-file":
        target.unlink(); os.link(secret, target)
    elif attack == "fifo":
        target.unlink(); os.mkfifo(target)
    elif attack == "writable-file":
        target.chmod(0o666)
    elif attack == "symlink-parent":
        target.unlink(); target.parent.rmdir(); target.parent.symlink_to(guard.home)
    else:
        target.parent.chmod(0o777)
    with pytest.raises((OSError, PermissionError)):
        guard.begin("candidate", "b" * 64, os.getpid(), outputs(guard))
    assert guard.load() is None
    assert secret.read_bytes() == b"unrelated file must remain unchanged"
    assert original == b"previous niri"


def test_external_or_traversing_hermes_home_cannot_redirect_watchdog(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    for location in (str(tmp_path.parent / "outside"), str(tmp_path / ".hermes/../../outside")):
        monkeypatch.setenv("HERMES_HOME", location)
        with pytest.raises(PermissionError):
            runpy.run_path(str(WATCHDOG))["ThemeGuard"]()


def test_invalid_parent_or_unlisted_output_cannot_arm_watchdog(guard):
    with pytest.raises(PermissionError):
        guard.begin("candidate", "b" * 64, 2**31, outputs(guard))
    with pytest.raises(PermissionError):
        guard.begin("candidate", "b" * 64, os.getpid(), outputs(guard) | {guard.home / "private": "no"})
    assert guard.load() is None


def test_atomic_journal_replace_failure_preserves_previous_state_and_removes_stage(guard, monkeypatch):
    token = activate(guard)
    old = (guard.root / "state.json").read_bytes()
    module = guard.save.__globals__
    original = module["os"].replace
    def fail(source, destination):
        if destination == guard.root / "state.json":
            raise OSError("injected journal publication failure")
        return original(source, destination)
    with monkeypatch.context() as local:
        local.setattr(module["os"], "replace", fail)
        with pytest.raises(OSError):
            guard.commit(token)
    assert (guard.root / "state.json").read_bytes() == old
    assert not list(guard.root.glob(".theme-*"))
    assert guard.load()["status"] == "pending"


def test_actual_engine_requires_verified_saved_bytes_and_arms_before_writing(guard):
    base = json.loads((ROOT / "linux/themes/herald-ocean/theme.json").read_text())
    base["name"] = "watchdog-design"
    manifest = (json.dumps(base, indent=2) + "\n").encode()
    revision = hashlib.sha256(manifest + b"\0").hexdigest()
    bundle = guard.home / ".config/herald-os/theme-versions/watchdog-design" / revision
    bundle.mkdir(parents=True, mode=0o700)
    (bundle / "theme.json").write_bytes(manifest)
    result = subprocess.run([sys.executable, str(ENGINE), "guarded-set", base["name"], "--revision", revision,
                             "--parent", str(os.getpid())], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt["pending"] is True
    assert guard.load()["watcher"] > 0
    assert guard.targets["name"].read_text() == "watchdog-design\n"
    assert "border" in guard.targets["niri"].read_text()
    # A CLI cannot pretend the shell has applied the saved preferences.
    with pytest.raises(PermissionError):
        guard.commit(receipt["theme_guard"])
    guard.recover(receipt["theme_guard"])
    # Change guaranteed bytes, independent of the built-in label spelling.
    (bundle / "theme.json").write_bytes(manifest + b" ")
    rejected = subprocess.run([sys.executable, str(ENGINE), "guarded-set", base["name"], "--revision", revision,
                               "--parent", str(os.getpid())], capture_output=True, timeout=5)
    assert rejected.returncode != 0
    assert guard.load()["status"] == "rolled_back"


def test_a_killed_watchdog_cannot_confirm_and_recovery_remains_independent(guard):
    token = activate(guard)
    watcher = guard.load()["watcher"]
    os.kill(watcher, signal.SIGKILL)
    module = guard.commit.__globals__
    wait_for(lambda: module["process_identity"](watcher) is None)
    with pytest.raises(PermissionError):
        guard.commit(token)
    guard.recover(token)
    assert guard.load()["status"] == "rolled_back"


def test_bootc_style_home_alias_keeps_private_outputs_at_canonical_anchor(guard, monkeypatch):
    alias = guard.home / "home-alias"
    alias.symlink_to(guard.home, target_is_directory=True)
    monkeypatch.setenv("HOME", str(alias))
    monkeypatch.setenv("HERMES_HOME", str(alias / ".hermes"))
    reopened = runpy.run_path(str(WATCHDOG))["ThemeGuard"]()
    assert reopened.home == guard.home and reopened.targets == guard.targets
    token = activate(reopened)
    reopened.recover(token)
    assert reopened.preferences()["themeName"] == "previous"


def test_session_start_recovers_before_compositor_reads_theme_include(guard):
    activate(guard)
    tools = guard.home / "bin"
    tools.mkdir(mode=0o700)
    # Unit-level compositor substitutes record launch order; real compositor and
    # renderer acceptance is the separate virtual Wayland gate.
    for name, body in {"niri": 'cp "$HOME/.config/niri/theme.kdl" "$HOME/observed-theme"',
                       "cage": 'cp "$HOME/.config/niri/theme.kdl" "$HOME/observed-theme"',
                       "herald-os": 'exit 0'}.items():
        target = tools / name
        target.write_text("#!/bin/sh\n" + body + "\n")
        target.chmod(0o700)
    (guard.home / ".config/niri/herald-os.kdl").write_text("explicit unit fixture")
    env = {"HOME": str(guard.home), "HERMES_HOME": str(guard.hermes),
           "PATH": str(tools) + ":" + str(ENGINE.parent) + ":/usr/bin:/bin", "HERALD_OS_NIRI_NESTED": "0"}
    result = subprocess.run(["bash", str(ROOT / "linux/session/herald-os-compositor")], env=env,
                            capture_output=True, timeout=8)
    assert result.returncode == 0
    assert (guard.home / "observed-theme").read_text() == "previous niri"
    assert guard.load()["status"] == "rolled_back"
