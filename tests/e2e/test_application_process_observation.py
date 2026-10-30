"""Actual /proc exit behavior in the disposable systemd probe's PID observer."""
import importlib.util
from pathlib import Path
import subprocess


spec = importlib.util.spec_from_file_location('application_unit_probe',
    Path(__file__).resolve().parents[2] / 'linux/haos/probes/run_application_unit.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_exited_snapshot_member_cannot_hide_real_long_lived_child():
    exited = subprocess.Popen(['/usr/bin/true'])
    exited.wait(timeout=5)
    assert not Path(f'/proc/{exited.pid}').exists()
    live = subprocess.Popen(['/usr/bin/sleep', '30'])
    try:
        assert probe.live_process_names([exited.pid, live.pid]) == {live.pid: 'sleep'}
        assert live.poll() is None
    finally:
        live.terminate(); live.wait(timeout=5)
    assert probe.live_process_names([exited.pid, live.pid]) == {}
