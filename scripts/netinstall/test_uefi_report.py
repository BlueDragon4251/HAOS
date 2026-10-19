"""Regression tests for xorriso boot reports from HAOS GitHub Actions."""
import unittest
from verify_uefi import contains_uefi_boot_entry

class UEFIBootReportTest(unittest.TestCase):
    def test_fedora_44_bios_plus_uefi(self):
        report = """Boot record  : El Torito , MBR isohybrid cyl-align-on GPT
El Torito boot img :   1  BIOS  y   none  0x0000  0x00      4        4002
El Torito boot img :   2  UEFI  y   none  0x0000  0x00  15852          39
El Torito boot img :   3  UEFI  y   none  0x0000  0x00  33776        4021
El Torito img path :   2  /isolinux/efiboot.img
"""
        self.assertTrue(contains_uefi_boot_entry(report))

    def test_reject_bios_only(self):
        report = """Boot record  : El Torito , MBR isohybrid cyl-align-on GPT
El Torito boot img :   1  BIOS  y   none  0x0000  0x00      4        4002
"""
        self.assertFalse(contains_uefi_boot_entry(report))

    def test_reject_efi_filename_without_boot_entry(self):
        self.assertFalse(contains_uefi_boot_entry(
            "El Torito img path :   2 /isolinux/efiboot.img"
        ))
