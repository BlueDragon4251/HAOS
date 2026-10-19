"""Regression guard for the installed, real tty2 recovery console.

A PTY-only enrollment fixture passes even when systemd cannot attach the actual
physical virtual terminal. PrivateDevices=yes made HAOS fail with 208/STDIN
before the recovery program could start on a real laptop.
"""

from configparser import ConfigParser
from pathlib import Path


def test_recovery_service_can_attach_tty2_without_exposing_other_devices():
    unit = Path(__file__).resolve().parents[1] / "haos-recovery.service"
    config = ConfigParser(interpolation=None)
    config.optionxform = str
    config.read_string(unit.read_text())
    service = config["Service"]

    assert service["StandardInput"] == "tty"
    assert service["StandardOutput"] == "tty"
    assert service["StandardError"] == "tty"
    assert service["TTYPath"] == "/dev/tty2"
    assert service["PrivateDevices"] == "no"
    assert service["DevicePolicy"] == "closed"
    assert service["DeviceAllow"] == "/dev/tty2 rw"
    assert service["ExecStart"] == "/usr/bin/python3 -I /usr/lib/haos/recovery-console.py"
    assert config["Unit"]["Conflicts"] == "getty@tty2.service"
