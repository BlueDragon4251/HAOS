"""Failure reporting must never power off an unmarked machine or disclose a token."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location("guest_diagnostics", Path(__file__).with_name("haos_guest_diagnostics.py"))
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


@pytest.mark.parametrize("uid,product,marker", [(1000, "haos-acceptance", True), (0, "other-machine", True),
                                               (0, "haos-acceptance", False)])
def test_unmarked_machine_cannot_be_powered_off(monkeypatch, uid, product, marker):
    monkeypatch.setattr(diagnostics.os, "geteuid", lambda: uid)
    monkeypatch.setattr(Path, "read_text", lambda self: product)
    monkeypatch.setattr(Path, "is_file", lambda self: marker)
    monkeypatch.setattr(diagnostics.subprocess, "run", lambda *a, **kw: pytest.fail("untrusted machine command"))
    with pytest.raises(PermissionError):
        diagnostics.main()


def test_successful_guest_does_not_run_failure_commands(monkeypatch):
    monkeypatch.setattr(diagnostics, "require_disposable_guest", lambda: None)
    monkeypatch.setenv("SERVICE_RESULT", "success")
    monkeypatch.setattr(diagnostics.subprocess, "run", lambda *a, **kw: pytest.fail("success invoked failure handler"))
    diagnostics.main()


def test_backend_credential_is_redacted_and_logs_are_bounded(monkeypatch):
    secret = "fixture-secret-credential"
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "read_text", lambda self: secret)
    monkeypatch.setattr(diagnostics.subprocess, "run", lambda args, **kw:
        subprocess.CompletedProcess(args, 1, "x" * 60000 + secret, "failure " + secret))
    reports = diagnostics.collect()
    assert all(secret not in report["output"] and len(report["output"]) <= 48000 for report in reports)
    assert all("[REDACTED]" in report["output"] and report["returncode"] == 1 for report in reports)


def test_startup_failure_keeps_backend_journal_capacity_and_listener_separate(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        assert kwargs == {"capture_output": True, "text": True, "timeout": 20, "check": False}
        return subprocess.CompletedProcess(args, 0, "fixed metadata", "")
    monkeypatch.setattr(diagnostics.subprocess, "run", run)
    reports = diagnostics.collect()
    assert len(reports) == 6
    assert commands[2][-2:] == ["--unit", "haos-hermes.service"]
    assert commands[3][-3:] == ["/", "/var", "/sysroot"]
    assert commands[4][-3:] == ["sport", "=", ":9119"]
    assert "MainPID" in commands[1][-1] and "CPUUsageNSec" in commands[1][-1]
    assert not any("--all" in args or "--processes" in args for args in commands)


@pytest.mark.parametrize("error", [OSError("fixture"), subprocess.TimeoutExpired("journalctl", 20)])
def test_unavailable_diagnostics_still_report_original_failure_and_power_off(monkeypatch, capsys, error):
    monkeypatch.setattr(diagnostics, "require_disposable_guest", lambda: None)
    monkeypatch.setenv("SERVICE_RESULT", "timeout")
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if "poweroff" not in args:
            raise error
        assert "HAOS_ACCEPTANCE_FAILED" in capsys.readouterr().out
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(diagnostics.subprocess, "run", run)
    diagnostics.main()
    assert commands[-1] == ["systemctl", "--no-block", "poweroff"]
