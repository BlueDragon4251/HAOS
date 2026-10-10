"""Real diskless QEMU probes, distinct from installed-OS acceptance."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("qemu_runtime", Path(__file__).parents[3] / "scripts/haos-qemu-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_real_tcg_machine_initializes():
    result = runtime.probe("tcg,thread=multi")
    print(json.dumps(result))
    assert result["usable"], result


def test_real_acceleration_selection():
    selected = runtime.select()
    print(json.dumps(selected))
    assert selected["accelerator"] in ("kvm", "tcg,thread=multi"), selected
    assert selected["attempts"][-1]["usable"]


def test_real_diskless_vm_supervision_has_live_metrics_and_bounded_shutdown(tmp_path):
    serial = tmp_path / "serial.log"
    serial.touch()
    # No disks, guest code or network. Deliberately hold the initialized VM at -S
    # to exercise actual supervisor telemetry/timeout without an installation.
    evidence, code = runtime.run_guest(["-machine", "q35", "-nodefaults", "-display", "none",
        "-m", "128", "-smp", "2", "-S", "-qmp", f"unix:{tmp_path / 'qmp.sock'},server=on,wait=off"],
        serial, 1)
    assert code == 124
    reports = evidence["recent_progress"]
    assert any(row["alive"] for row in reports)
    assert any(row.get("resident_bytes", 0) > 0 for row in reports)
    assert reports[-1]["phase_timed_out"] and not reports[-1]["alive"]
    assert len(evidence["launches"]) == 1
    print(json.dumps({"actual_diskless_vm_supervised": True, "live_metrics_recorded": True,
                      "timeout_not_success": True, "terminated_without_replay": True,
                      "installed_guest_acceptance": False}))
