#!/usr/bin/env python3
"""Real virtual Wayland + production Chromium/socket gates, no provider claim.

Starts only our own non-root headless compositor. Artifacts exclude raw protocol
logs and the disposable mission database; no host display is used or captured.
"""
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import time


REPO = Path(__file__).resolve().parents[1]


def stop(process):
    if process is None:
        return
    # A private new process group also bounds orphan Chromium/controller children.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
    # The group can still contain descendants after the launcher exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def source():
    return {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "work_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip()),
    }


def bounded_file(path, limit):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_size > limit:
        raise AssertionError("invalid disposable artifact")
    return path.read_bytes()


def main():
    if os.environ.get("HAOS_DISPOSABLE_SCREEN_TEST") != "1" or os.geteuid() == 0:
        raise PermissionError("explicit non-root disposable fixture required")
    root = Path(tempfile.mkdtemp(prefix="haos-wayland-gate-"))
    root.chmod(0o700)
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    home = root / "home"
    home.mkdir(mode=0o700)
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700)
    env = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "HOME": str(home), "XDG_RUNTIME_DIR": str(runtime)}
    compositor_env = dict(env)
    for incoming, outgoing in (("HAOS_TEST_WESTON_LIBRARY_PATH", "LD_LIBRARY_PATH"), ("WESTON_MODULE_MAP", "WESTON_MODULE_MAP")):
        if incoming in os.environ:
            compositor_env[outgoing] = os.environ[incoming]
    weston = os.environ.get("HAOS_TEST_WESTON", "weston")
    version = subprocess.check_output([weston, "--version"], env=compositor_env, text=True, timeout=5).strip()
    major = int(re.search(r"\b(\d+)\.", version).group(1))
    flags = ["--backend=headless", "--renderer=pixman"] if major >= 14 else ["--backend=headless-backend.so", "--use-pixman"]
    flags += ["--width=1024", "--height=768", "--idle-time=0", "--socket=haos-disposable-wayland", "--no-config",
              "--shell=" + os.environ.get("HAOS_TEST_WESTON_SHELL", "kiosk-shell.so")]
    compositor = client = None
    identity = source()
    try:
        with (root / "compositor.log").open("wb") as log:
            compositor = subprocess.Popen([weston, *flags], env=compositor_env, stdout=log, stderr=log, start_new_session=True)
        display = runtime / "haos-disposable-wayland"
        deadline = time.monotonic() + 10
        while not display.exists():
            if compositor.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("virtual compositor failed to start")
            time.sleep(0.05)
        metadata = display.lstat()
        assert stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.geteuid()
        # A real connect on our private socket; DISPLAY is absent from child env.
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(str(display))
        client_env = {**env, "WAYLAND_DISPLAY": display.name, "WAYLAND_DEBUG": "1", "HAOS_DISPOSABLE_SCREEN_TEST": "1"}
        electron = REPO / "node_modules/electron/dist/electron"
        reports, protocol = {}, {}
        for name, script, prefix, files in (
            ("browser", "test-gui-broker.mjs", "haos-gui-broker-", ("gui-broker.json", "disposable-form.jpg")),
            ("integration", "test-gui-integration.mjs", "haos-gui-integration-", ("gui-integration.json",)),
        ):
            log_path = root / (name + ".log")
            with log_path.open("wb") as log:
                client = subprocess.Popen([str(electron), "--ozone-platform=wayland", "--disable-gpu",
                    str(REPO / "apps/desktop/scripts" / script)], cwd=REPO, env=client_env, stdout=log, stderr=log, start_new_session=True)
            code = client.wait(timeout=75)
            if code != 0:
                # Only the explicitly disposable probe's own bounded failure label,
                # never complete protocol logs, profiles, sessions or journal data.
                output = bounded_file(log_path, 8 * 1024 * 1024).decode('utf-8', errors='replace')
                print(f'Disposable {name} process exit: {code}', flush=True)
                phases = re.findall(r'^HAOS_GUI_FIXTURE_PHASE ([a-z-]{1,64})$', output, re.M)
                if phases:
                    print('Disposable GUI last phase: ' + phases[-1], flush=True)
                for line in output.splitlines():
                    if line.startswith(('Actual GUI capability gate failed:', 'Actual native/socket GUI gate failed:', 'Error:', 'SyntaxError:', 'TypeError:', 'ReferenceError:')):
                        print(line[:640], flush=True)
                raise AssertionError('real Wayland GUI probe failed: ' + name)
            stop(client)
            client = None
            assert compositor.poll() is None, "compositor exited during GUI work"
            output = bounded_file(log_path, 8 * 1024 * 1024).decode("utf-8", errors="replace")
            receipts = [json.loads(line) for line in output.splitlines() if line.startswith('{"evidence":')]
            assert len(receipts) == 1 and all(receipts[0][key] == value for key, value in identity.items())
            artifact = Path(receipts[0]["evidence"])
            assert artifact.parent.parent == Path("/tmp") and artifact.parent.name.startswith(prefix)
            assert artifact.resolve() == artifact and artifact.name == "evidence"
            assert artifact.stat().st_uid == os.geteuid() and not artifact.stat().st_mode & 0o077
            for filename in files:
                payload = bounded_file(artifact / filename, 131072)
                target = evidence / filename
                target.write_bytes(payload)
                target.chmod(0o600)
            reports[name] = {key: receipts[0][key] for key in ("checks", "source_commit")}
            assert reports[name]["checks"] and all(value is True for value in reports[name]["checks"].values())
            # Chromium/Wayland protocol uses '#' or '@' object IDs across versions.
            titles = len(re.findall(r'xdg_toplevel[@#]\d+\.set_title\("HAOS Mission ', output))
            commits = len(re.findall(r'wl_surface[@#]\d+\.commit\(', output))
            assert titles > 0 and commits > 0, "no real mission surface protocol"
            protocol[name] = {"mission_toplevels": titles, "surface_commits": commits}
        report = {**identity, "weston": version, "actual_virtual_wayland": True,
                  "installed_niri": False, "physical_hardware": False, "real_model_turn": False,
                  "session_is_explicit_fixture": True, "protocol": protocol, "gates": reports}
        (evidence / "virtual-wayland.json").write_text(json.dumps(report, indent=2) + "\n")
        (evidence / "virtual-wayland.json").chmod(0o600)
        print(json.dumps({"evidence": str(evidence), **report}))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"evidence={evidence}\n")
    finally:
        stop(client)
        stop(compositor)


if __name__ == "__main__":
    main()
