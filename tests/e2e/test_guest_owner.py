"""Owner fixture provisioning must fail before any mutation outside a marked guest."""

import ast
import importlib.util
import os
from pathlib import Path
import stat
import sys
import subprocess
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "linux/haos"))
spec = importlib.util.spec_from_file_location("guest_owner_probe", Path(__file__).with_name("haos_guest.py"))
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def test_progress_contains_only_fixed_phase_and_elapsed_time(monkeypatch, capsys):
    monkeypatch.setenv("HAOS_PRIVATE_FIXTURE", "never-log-this-credential")
    monkeypatch.setattr(guest.time, "monotonic", lambda: guest.PROBE_STARTED + 123.456)
    guest.progress("live-ledger-backup-restore")
    output = capsys.readouterr().out
    import json
    assert json.loads(output.split("=", 1)[1]) == {"phase": "live-ledger-backup-restore", "elapsed_seconds": 123.46}
    assert "never-log-this-credential" not in output and "HAOS_ACCEPTANCE_JSON" not in output
    with pytest.raises(ValueError, match="unknown acceptance phase"):
        guest.progress("never-log-this-credential")
    assert not capsys.readouterr().out


def test_guest_budget_leaves_time_for_boot_diagnostics_and_shutdown():
    # An expanded guest matrix must fit inside the outer QEMU phase; otherwise
    # SIGTERM kills diagnostics and hides the original failure.
    import re
    text = (Path(__file__).resolve().parents[2] / "scripts/test-haos-iso.sh").read_text()
    unit = text.split("cat >/etc/systemd/system/haos-acceptance.service <<'UNIT'", 1)[1].split("\nUNIT", 1)[0]
    start = re.search(r"^TimeoutStartSec=(\d+)min$", unit, re.M)
    stop = re.search(r"^TimeoutStopSec=(\d+)s$", unit, re.M)
    host = re.search(r'run_vm "boot-\$stage" (\d+) ', text)
    assert start and stop and host
    assert 0 < int(start[1]) * 60 + int(stop[1]) + 300 < int(host[1]) <= 1800


@pytest.mark.parametrize("file,function,variable", [
    ("tests/e2e/haos_guest.py", "sandbox_probe", "script"),
    ("tests/e2e/haos_guest.py", "disconnected_volume_probe", "script"),
    ("linux/haos/probes/test_kernel.py", "run_agent_filesystem_probe", "probe"),
])
def test_actual_embedded_filesystem_programs_compile_before_privileged_launch(file, function, variable):
    # Compiling the outer module does not compile strings later passed to -c.
    path = Path(__file__).resolve().parents[2] / file
    fn = next(node for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == function)
    programs = [ast.literal_eval(node.value) for node in fn.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)]
    assert len(programs) == 1
    compile(programs[0], file + ":" + function, "exec")


def test_actual_installed_observer_http_program_compiles_before_launch():
    module = ast.parse(Path(guest.__file__).read_text())
    assignment = next(node for node in ast.walk(module) if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "observer_dashboard_code" for t in node.targets))
    assert isinstance(assignment.value, ast.Call) and assignment.value.func.attr == "join"
    compile("\n".join(ast.literal_eval(assignment.value.args[0])), "installed-observer-dashboard", "exec")


@pytest.mark.parametrize("uid,product,owner,mode", [
    (1000, "haos-acceptance", 0, stat.S_IFREG | 0o644),
    (0, "actual-workstation", 0, stat.S_IFREG | 0o644),
    (0, "haos-acceptance", 1000, stat.S_IFREG | 0o644),
    (0, "haos-acceptance", 0, stat.S_IFLNK | 0o777),
    (0, "haos-acceptance", 0, stat.S_IFREG | 0o666),
])
def test_owner_provisioning_cannot_mutate_an_unmarked_or_forged_guest(monkeypatch, uid, product, owner, mode):
    monkeypatch.setattr(guest.os, "geteuid", lambda: uid)
    monkeypatch.setattr(Path, "read_text", lambda self: product)
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_uid=owner, st_mode=mode))
    monkeypatch.setattr(guest.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("untrusted guest spawned root enrollment"))
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: pytest.fail("untrusted guest created owner credentials"))
    with pytest.raises(PermissionError):
        guest.owner_authentication_proof(first_boot=True)
    with pytest.raises(PermissionError):
        guest.sandbox_probe("rw")
    with pytest.raises(PermissionError):
        guest.disconnected_volume_probe()
    with pytest.raises(PermissionError):
        guest.namespace_probe([], "never executed", [], "forged-guest")


def test_sandbox_failure_reports_bounded_redacted_stderr_without_command_or_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(guest, "require_disposable_guest", lambda: None)
    monkeypatch.setattr(guest, "ROOT", tmp_path)
    monkeypatch.setattr(guest, "trusted_json", lambda path: {"grants": []})
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=12345, pw_gid=12345))
    descriptors = []
    def failed(args, **kwargs):
        descriptors.extend(kwargs["pass_fds"])
        assert kwargs["timeout"] == 60
        return subprocess.CompletedProcess(args, 1, "stdout-private-fixture",
            "x" * 10000 + "\nPermissionError: acceptance-unused-token")
    monkeypatch.setattr(guest.subprocess, "run", failed)
    with pytest.raises(RuntimeError) as error:
        guest.sandbox_probe("rw")
    message = str(error.value)
    assert "PermissionError" in message and "[REDACTED]" in message
    assert len(message) < 2100 and "acceptance-unused-token" not in message
    assert "stdout-private-fixture" not in message and "--reuid" not in message
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_namespace_configuration_failure_closes_its_actual_fixture_descriptor(tmp_path, monkeypatch):
    monkeypatch.setattr(guest, "require_disposable_guest", lambda: None)
    monkeypatch.setattr(guest, "ROOT", tmp_path)
    descriptors = []
    def reject(grants, fd, **kwargs):
        descriptors.append(fd)
        raise ValueError("invalid namespace plan")
    monkeypatch.setattr(guest, "command", reject)
    monkeypatch.setattr(guest.subprocess, "run", lambda *a, **k: pytest.fail("rejected plan launched a process"))
    with pytest.raises(ValueError, match="namespace plan"):
        guest.namespace_probe([], "never executed", [], "configuration-failure")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
