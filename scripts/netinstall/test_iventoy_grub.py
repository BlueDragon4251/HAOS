"""Regression tests for iVentoy-compatible GRUB menu generation."""
import unittest
from fix_livecd_grub import fix_grub_text
from verify_live_grub import verify


class IventoyGrubTest(unittest.TestCase):
    LEGACY = """menuentry 'Start HAOS' {
  linuxefi /isolinux/vmlinuz0 root=live:LABEL=HAOS-DUAL-44
  initrdefi /isolinux/initrd0.img
}
"""
    NATIVE = """menuentry 'Start HAOS' {
  linux /isolinux/vmlinuz0 root=live:LABEL=HAOS-DUAL-44
  initrd /isolinux/initrd0.img
}
"""

    def test_patch_generated_uefi_menu(self):
        result = fix_grub_text(self.LEGACY)
        self.assertEqual(result, self.NATIVE)
        verify(result)

    def test_native_fedora_menu_requires_no_changes(self):
        self.assertEqual(fix_grub_text(self.NATIVE), self.NATIVE)

    def test_reject_missing_kernel_initrd(self):
        with self.assertRaises(ValueError):
            fix_grub_text("menuentry 'no kernel' {}")

    def test_reject_nonmatching_source_layout_no_longer_relevant(self):
        # This checks generated menu text, independent of distro Python source.
        self.assertEqual(fix_grub_text(self.LEGACY), self.NATIVE)

    def test_preserve_unrelated_occurrences(self):
        menu = self.LEGACY + "# text linuxefi /initrdefi is harmless here\n"
        result = fix_grub_text(menu)
        self.assertIn("# text linuxefi /initrdefi", result)
        verify(result)

    def test_reject_incompatible_generated_menu(self):
        with self.assertRaises(ValueError):
            verify(self.LEGACY)


if __name__ == "__main__":
    unittest.main()
