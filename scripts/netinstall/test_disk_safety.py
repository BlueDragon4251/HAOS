#!/usr/bin/env python3
"""Disk safety regression tests, including PXE and a token USB drive."""
import runpy
import unittest
from pathlib import Path

mod = runpy.run_path(str(Path(__file__).with_name("haos-disk-safety.py")))
eligible = mod["is_eligible"]

class DiskSafetyTest(unittest.TestCase):
    def drive(self, **overrides):
        d = {"path": "/dev/nvme0n1", "type": "disk",
             "size": 256 * 1024**3, "tran": "nvme", "rm": False,
             "ro": False, "model": "Internal NVMe"}
        d.update(overrides)
        return d

    def test_internal_nvme_allowed(self):
        self.assertTrue(eligible(self.drive()))

    def test_token_usb_rejected_even_if_large(self):
        self.assertFalse(eligible(self.drive(path="/dev/sda", tran="usb")))

    def test_121mb_usb_rejected(self):
        self.assertFalse(eligible(self.drive(path="/dev/sda", tran="usb", size=121 * 1024**2)))

    def test_removable_card_rejected(self):
        self.assertFalse(eligible(self.drive(tran=None, rm=True)))

    def test_too_small_rejected(self):
        self.assertFalse(eligible(self.drive(size=8 * 1024**3)))

    def test_read_only_rejected(self):
        self.assertFalse(eligible(self.drive(ro=True)))

    def test_partition_rejected(self):
        self.assertFalse(eligible(self.drive(type="part", path="/dev/nvme0n1p1")))

    def test_large_virtual_nbd_drive_rejected(self):
        self.assertFalse(eligible(self.drive(path="/dev/nbd0", tran=None)))

    def test_large_loop_drive_rejected(self):
        self.assertFalse(eligible(self.drive(path="/dev/loop0", tran=None)))

    def test_large_device_mapper_drive_rejected(self):
        self.assertFalse(eligible(self.drive(path="/dev/dm-0", tran=None)))

    def test_ram_and_zram_rejected(self):
        self.assertFalse(eligible(self.drive(path="/dev/zram0", tran=None)))
        self.assertFalse(eligible(self.drive(path="/dev/ram0", tran=None)))

    def test_internal_sata_allowed(self):
        self.assertTrue(eligible(self.drive(path="/dev/sda", tran="sata")))

    def test_missing_path_rejected(self):
        self.assertFalse(eligible(self.drive(path="")))

if __name__ == "__main__":
    unittest.main()
