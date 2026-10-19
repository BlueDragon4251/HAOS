"""Regression: fresh Anaconda first boot must open native owner GUI automatically.

This is a static integration contract for target wiring. The separate real
installed-guest / VT1 graphics acceptance remains mandatory before stable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BOOT = ROOT / "linux/image/firstboot.sh"
SETUP = ROOT / "linux/haos/haos-setup-desktop.service"
FIRSTBOOT = ROOT / "linux/image/herald-os-firstboot.service"
INSTALL = ROOT / "linux/haos/install.sh"


def test_owner_gui_starts_from_initial_multi_user_target():
    service = SETUP.read_text(encoding="utf-8")
    firstboot = FIRSTBOOT.read_text(encoding="utf-8")
    assert "WantedBy=multi-user.target" in service
    assert "After=systemd-user-sessions.service herald-os-firstboot.service" in service
    assert "Requires=herald-os-firstboot.service" in service
    assert "ConditionPathExists=/etc/haos/enabled" in service
    assert "ExecCondition=/usr/bin/haos-setup-gate prompt" in service
    assert "Before=greetd.service" in service
    assert "WantedBy=multi-user.target" in firstboot
    assert "Before=greetd.service" in firstboot
    assert "systemctl enable haos-setup-desktop.service" in INSTALL.read_text(encoding="utf-8")


def test_firstboot_never_launches_graphical_target_before_setup_state_exists():
    script = BOOT.read_text(encoding="utf-8")
    assert "systemctl set-default graphical.target" in script
    assert "systemctl --no-block start graphical.target" not in script
    assert "systemctl start graphical.target" not in script
    assert "python3 -m haos.initialize" in script
    assert 'date -Is >"$STATE/firstboot-done"' in script


def test_wizard_is_behind_gate_and_separate_recovery_stays_available():
    setup = SETUP.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/bash /usr/lib/haos/setup-display.sh" in setup
    assert "StandardInput=tty-force" in setup
    assert "TTYPath=/dev/tty1" in setup
    assert "Conflicts=getty@tty1.service" in setup
    # Owner onboarding creates /home/<owner> and normal observer files; the
    # trusted root-only wizard cannot use systemd ProtectHome=yes.
    assert "ProtectHome=no" in setup
    assert "ProtectHome=yes" not in "\n".join(line for line in setup.splitlines()
                                         if not line.lstrip().startswith("#"))
    assert "NoNewPrivileges=yes" in setup
    assert "ExecCondition=/usr/bin/haos-setup-gate prompt" in setup
    assert "TTYPath=/dev/tty8" not in setup
    assert "chvt 1" in (ROOT / "linux/haos/setup-gui-session.sh").read_text(encoding="utf-8")
    display = (ROOT / "linux/haos/setup-display.sh").read_text(encoding="utf-8")
    assert "Xorg :8 vt1" in display
    assert "Xorg :8 vt8" not in display
    installed = INSTALL.read_text(encoding="utf-8")
    assert "systemctl enable haos-setup-desktop.service" in installed
    assert "haos-recovery.service" in installed
    assert "ExecCondition=/usr/bin/haos-setup-gate desktop" in installed
