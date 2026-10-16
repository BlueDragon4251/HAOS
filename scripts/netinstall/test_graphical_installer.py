#!/usr/bin/env python3
"""Headless tests for actual graphical installer backend behavior."""
import threading
import unittest
from unittest import mock
import subprocess
import haos_install_core as core

class GraphicalInstallerCoreTests(unittest.TestCase):
    def test_usb_list_has_only_filesystem_partitions(self):
        sample = [{"path":"/dev/sda","type":"disk","tran":"usb","fstype":None,"children":[
            {"path":"/dev/sda1","type":"part","fstype":"vfat","size":120000000}]},
            {"path":"/dev/nbd0","type":"disk","size":100000000000,"fstype":"ext4"},
            {"path":"/dev/nvme0n1","type":"disk","tran":"nvme","children":[
                {"path":"/dev/nvme0n1p1","type":"part","fstype":"ext4"}]}]
        with mock.patch.object(core, "_lsblk", return_value=sample):
            self.assertEqual([d["path"] for d in core.token_partitions()], ["/dev/sda1"])

    def test_https_401_means_registry_reachable(self):
        with mock.patch.object(core, "execute", side_effect=["20.205.119.73", "401"]):
            self.assertIn("erreichbar", core.check_network())

    def test_tcp_timeout_has_useful_recovery(self):
        with mock.patch.object(core, "execute", side_effect=[
            "20.205.119.73", core.InstallerError("i/o timeout")]):
            with self.assertRaises(core.InstallerError) as captured:
                core.check_network()
        self.assertIn("Port 443", str(captured.exception))
        self.assertIn("PXE", str(captured.exception))
        self.assertIn("Gateway", str(captured.exception))

    def test_invalid_tokens_rejected(self):
        for token in ("", "a b", "\n", "x"*8193):
            with self.assertRaises(core.InstallerError):
                core.check_token(token)

    def test_digest_format_rejects_unpinned(self):
        self.assertIsNone(core.IMAGE_PATTERN.fullmatch("ghcr.io/bluedragon4251/haos:dev-test"))

    def test_cancellable_command_does_not_hang(self):
        canceled = threading.Event()
        canceled.set()
        with self.assertRaisesRegex(core.InstallerError, "abgebrochen"):
            core.execute(["/usr/bin/sleep", "5"], timeout=6, cancel_event=canceled)

    def test_actual_short_timeout(self):
        with self.assertRaisesRegex(core.InstallerError, "Zeitüberschreitung"):
            core.execute(["/usr/bin/sleep", "5"], timeout=0.15)

    def test_disk_selection_uses_existing_validator(self):
        with mock.patch.object(core, "ROOT", core.ROOT):
            # Real safety module (mock only the lsblk subprocess).
            with mock.patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["lsblk"], returncode=0,
                    stdout='{"blockdevices":[{"path":"/dev/nbd0","type":"disk","size":64000000000,"rm":0,"ro":0},'
                           '{"path":"/dev/nvme0n1","type":"disk","size":512000000000,"tran":"nvme","rm":0,"ro":0}]}'
                )
                self.assertEqual([d["path"] for d in core.internal_disks()], ["/dev/nvme0n1"])


if __name__ == "__main__":
    unittest.main()
