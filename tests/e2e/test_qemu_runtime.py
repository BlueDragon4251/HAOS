"""Acceleration regression tests; these are not installed-guest evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location("qemu_runtime", Path(__file__).parents[2] / "scripts/haos-qemu-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
QMP = '{"QMP":{}}\n{"return":{}}\n{"return":{}}\n'


def test_actual_kvm_handshake():
    def run(args, **kwargs):
        assert "kvm" in args and "host" in args
        assert not any("drive" in arg for arg in args)
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(args, 0, QMP, "")
    assert runtime.probe("kvm", run)["usable"]


@pytest.mark.parametrize("result", [
    (1, "", "Could not access KVM kernel module: Permission denied"),
    (0, "", ""),
    (0, '{"QMP":{}}\n{"error":{"class":"GenericError"}}\n', ""),
    (-9, QMP, ""),
])
def test_reject_failed_or_incomplete_vm(result):
    assert not runtime.probe("kvm", lambda args, **kw: subprocess.CompletedProcess(args, *result))["usable"]


def test_hung_probe_is_bounded():
    def run(args, **kw):
        raise subprocess.TimeoutExpired(args, kw["timeout"])
    assert runtime.probe("kvm", run)["usable"] is False


def test_permission_denial_falls_back_to_checked_tcg():
    attempted = []
    def probe(accelerator):
        attempted.append(accelerator)
        return {"accelerator": accelerator, "usable": accelerator.startswith("tcg"),
                "stderr": "Permission denied" if accelerator == "kvm" else ""}
    selected = runtime.select(probe)
    assert attempted == ["kvm", "tcg,thread=multi"]
    assert selected["cpu"] == "max" and selected["accelerator"] == "tcg,thread=multi"
    assert selected["attempts"][0]["stderr"] == "Permission denied"


def test_no_fallback_needed_with_working_kvm():
    calls = []
    def probe(accelerator):
        calls.append(accelerator)
        return {"usable": True}
    assert runtime.select(probe)["cpu"] == "host"
    assert calls == ["kvm"]


def test_failed_tcg_is_not_success():
    selected = runtime.select(lambda accelerator: {"usable": False})
    assert selected["accelerator"] is None and len(selected["attempts"]) == 2


def test_each_phase_rechecks_kvm():
    calls = []
    def probe(accelerator):
        calls.append(accelerator)
        return {"usable": len(calls) == 1 or accelerator.startswith("tcg")}
    assert runtime.select(probe)["accelerator"] == "kvm"
    assert runtime.select(probe)["accelerator"] == "tcg,thread=multi"


def test_actual_kvm_start_failure_can_fall_back_before_guest_boot(tmp_path):
    calls = []
    def run(args, **kw):
        calls.append(args)
        if "kvm" in args:
            return subprocess.CompletedProcess(args, 1, "", "failed to initialize kvm: Permission denied")
        return subprocess.CompletedProcess(args, 0, "", "")
    evidence, code = runtime.run_guest(["-smp", "2"], tmp_path / "serial.log", 60,
                                      run=run, probe_vm=lambda a: {"accelerator": a, "usable": True})
    assert code == 0 and len(calls) == 2
    assert evidence["accelerator"] == "tcg,thread=multi"
    assert evidence["launches"][0]["returncode"] == 1


@pytest.mark.parametrize("error,code,serial", [
    ("failed to initialize kvm: Permission denied", 1, "guest already started"),
    ("disk I/O error", 1, ""),
    ("failed to initialize kvm: Permission denied", 124, ""),
])
def test_guest_errors_and_partial_installations_are_never_retried(tmp_path, error, code, serial):
    path = tmp_path / "serial.log"
    path.write_text(serial)
    calls = []
    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, code, "", error)
    evidence, status = runtime.run_guest([], path, 60, run=run,
        probe_vm=lambda a: {"accelerator": a, "usable": True})
    assert status == code and len(calls) == 1


def test_vm_timeout_is_a_failure_without_replay(tmp_path):
    def run(args, **kw):
        raise subprocess.TimeoutExpired(args, kw["timeout"])
    evidence, code = runtime.run_guest([], tmp_path / "serial.log", 60, run=run,
        probe_vm=lambda a: {"accelerator": a, "usable": True})
    assert code == 124 and len(evidence["launches"]) == 1


def test_actual_supervisor_reports_only_own_process_metadata(tmp_path):
    serial = tmp_path / "private-serial.log"
    serial.write_text("private disposable serial message, never public")
    reports = []
    result = runtime.supervised_run([sys.executable, "-c", "import time; print('private disposable output'); time.sleep(.2)"],
        serial_log=serial, timeout=5, interval=.05, progress=reports.append,
        text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert len(reports) >= 3 and any(row["alive"] for row in reports)
    assert reports[-1]["returncode"] == 0 and not reports[-1]["alive"]
    assert all(row.get("serial_bytes") == serial.stat().st_size for row in reports)
    assert "private disposable" not in json.dumps(reports)
    assert str(tmp_path) not in json.dumps(reports)
    if sys.platform == "linux":
        assert any(row.get("resident_bytes", 0) > 0 for row in reports)
        assert any("cpu_seconds" in row for row in reports)


def test_actual_supervisor_timeout_terminates_its_own_group(tmp_path):
    reports = []
    serial = tmp_path / "serial.log"
    serial.touch()
    with pytest.raises(subprocess.TimeoutExpired):
        runtime.supervised_run([sys.executable, "-c", "import time; time.sleep(60)"],
            serial_log=serial, timeout=.15, interval=.05, progress=reports.append,
            text=True, capture_output=True, check=False)
    assert reports[-1]["phase_timed_out"] and not reports[-1]["alive"]
    with pytest.raises(ProcessLookupError):
        os.kill(reports[-1]["pid"], 0)
