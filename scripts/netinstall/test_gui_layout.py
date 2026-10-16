#!/usr/bin/env python3
"""Headless test of responsive geometry and always-available console path."""
import ast
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


class KioskLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = (HERE / "haos-gui.py").read_text()
        cls.ks = (HERE / "build-live-ks.py").read_text()
        cls.session = (HERE / "haos-xsession.sh").read_text()
        tree = ast.parse(cls.gui)
        method = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                      and item.name == "layout_for_screen")
        program = ast.Module(body=[method], type_ignores=[])
        ns = {}
        exec(compile(program, str(HERE / "haos-gui.py"), "exec"), ns)
        cls.layout = staticmethod(ns["layout_for_screen"])

    def test_small_uefi_resolution(self):
        c = self.layout(640, 480)
        self.assertTrue(c["compact"])
        self.assertLessEqual(c["heading"], 22)
        self.assertLessEqual(c["padx"], 24)
        self.assertLessEqual(c["pady"], 16)

    def test_normal_resolution(self):
        self.assertFalse(self.layout(1920, 1080)["compact"])

    def test_no_fixed_geometry(self):
        self.assertNotIn('geometry("1200x740")', self.gui)
        self.assertIn('self.winfo_screenwidth()', self.gui)
        self.assertIn('self.winfo_screenheight()', self.gui)
        self.assertIn('self.focus_force()', self.gui)

    def test_keyboard_shortcuts(self):
        for key in ('<KeyPress-1>', '<KeyPress-2>', '<F2>', '<F3>', '<F12>', '<Control-Shift-D>'):
            self.assertIn(key, self.gui)
        self.assertIn('self.stable_button.focus_force()', self.gui)

    def test_console_emergency_mode(self):
        self.assertIn('haos-installer-console.service', self.ks)
        self.assertIn('TTYPath=/dev/tty2', self.ks)
        self.assertIn('systemctl enable haos-installer-console.service', self.ks)

    def test_keyboard_layout_selector(self):
        self.assertIn('self.bind("<F4>", self.cycle_keyboard)', self.gui)
        self.assertIn('("Deutsch (AT)", "at")', self.gui)
        self.assertIn('setxkbmap', self.gui)
        self.assertIn("keyboard --vckeymap=de --xlayouts=at", self.ks)
        self.assertIn("setxkbmap -layout at", self.session)

    def test_nmtui_is_not_executed_through_bash(self):
        self.assertIn('else [path, *args]', self.gui)

    def test_input_stack(self):
        for package in ('openbox', 'xorg-x11-drv-evdev', 'xorg-x11-drv-libinput', 'xrandr'):
            self.assertIn(package, self.ks)
        self.assertIn('openbox --sm-disable', self.session)
        self.assertIn('/proc/bus/input/devices', self.session)


if __name__ == "__main__":
    unittest.main()
