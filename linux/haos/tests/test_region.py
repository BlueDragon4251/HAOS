"""No model/desktop path may request arbitrary root locale changes."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos import region


class RegionPolicyTest(unittest.TestCase):
    def test_layouts_and_locale_allowlist(self):
        with patch.object(region.os, "geteuid", return_value=0), \
             patch.object(region, "localectl") as runner, \
             patch("haos.owner.audit"):
            response = region.owner_region(SimpleNamespace(region_action="apply", language="de_AT.UTF-8", keyboard="at"))
            self.assertEqual(response["keyboard"], "at")
            self.assertEqual(runner.call_args_list[0].args, ("set-keymap", "de-latin1"))
            self.assertEqual(runner.call_args_list[1].args, ("set-x11-keymap", "at"))
            self.assertEqual(runner.call_args_list[2].args, ("set-locale", "LANG=de_AT.UTF-8"))

    def test_reject_injection_even_under_root(self):
        with patch.object(region.os, "geteuid", return_value=0), patch.object(region, "localectl") as runner:
            for language, keyboard in (("de_AT.UTF-8; echo bad", "at"), ("de_AT.UTF-8", "at;sh"),
                                       ("en_US.UTF-8", "../us"), ("en_AU.UTF-8", "us")):
                with self.assertRaises(ValueError):
                    region.owner_region(SimpleNamespace(region_action="apply", language=language, keyboard=keyboard))
            runner.assert_not_called()

    def test_locked_observer_cannot_write_system_locale(self):
        with patch.object(region.os, "geteuid", return_value=1000), patch.object(region, "localectl") as runner:
            with self.assertRaises(PermissionError):
                region.owner_region(SimpleNamespace(region_action="apply", language="de_AT.UTF-8", keyboard="at"))
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
