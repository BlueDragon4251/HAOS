"""Safe bootc channel and GHCR authentication state (no privileged execution)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos import update


class UpdatePolicyTest(unittest.TestCase):
    def test_fixed_registry_and_public_non_secret_receipt(self):
        self.assertEqual(update.CHANNELS["dev"], "ghcr.io/bluedragon4251/haos:dev-current")
        self.assertEqual(update.CHANNELS["stable"], "ghcr.io/bluedragon4251/haos:stable")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "status.json"
            receipt = update.publish("staged", channel="dev", auto_stage=True,
                                     reboot_required=True, path=dest)
            self.assertEqual(receipt["state"], "staged")
            self.assertTrue(receipt["reboot_required"])
            self.assertNotIn("token", dest.read_text().lower())
            self.assertFalse(dest.stat().st_mode & 0o077 == 0)

    def test_reject_arbitrary_channels_and_invalid_auth(self):
        with self.assertRaises(ValueError):
            update.publish("staged", channel="attacker", auto_stage=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with self.assertRaises(ValueError):
                update.persist_config({"channel": "host", "auto_stage": True}, path)
            self.assertEqual(update.load_config(path)["channel"], "unconfigured")
            update.persist_config({"channel": "dev", "auto_stage": False}, path)
            self.assertEqual(update.load_config(path)["channel"], "dev")
            path.unlink()
            path.symlink_to(Path(tmp) / "elsewhere")
            with self.assertRaises(PermissionError):
                update.load_config(path)
            with self.assertRaises(PermissionError):
                update.persist_config({"channel": "dev", "auto_stage": False}, path)

    def test_private_channel_needs_root_owned_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "auth.json"
            self.assertFalse(update.has_auth(f))
            f.write_text("{}")
            os.chmod(f, 0o644)
            self.assertFalse(update.has_auth(f))
            os.chmod(f, 0o600)
            self.assertEqual(update.has_auth(f), os.getuid() == 0)

    def test_unconfigured_watch_never_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(update, "root"), patch.object(update, "load_config", return_value={"channel": "unconfigured", "auto_stage": False}), \
                 patch.object(update, "publish", return_value={"state": "unconfigured"}) as publish, patch.object(update, "command") as command:
                self.assertEqual(update.watch(), {"state": "unconfigured"})
                command.assert_not_called()
                publish.assert_called_once()

    def test_dev_stage_does_not_reboot(self):
        with patch.object(update, "root"), patch.object(update, "load_config", return_value={"channel": "dev", "auto_stage": True}), \
             patch.object(update, "has_auth", return_value=True), \
             patch.object(update, "command", side_effect=["Update available", ""]), \
             patch.object(update, "publish", return_value={"state": "staged"}) as publish:
            self.assertEqual(update.watch(stage=True), {"state": "staged"})
            self.assertTrue(publish.call_args.kwargs["reboot_required"])


if __name__ == "__main__":
    unittest.main()
