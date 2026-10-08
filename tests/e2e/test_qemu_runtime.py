"""Acceleration regression tests; these are not installed-guest evidence."""
import importlib.util
from pathlib import Path
import subprocess

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
