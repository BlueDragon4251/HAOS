"""Regression tests for iVentoy-compatible GRUB menu generation."""
import unittest
from fix_livecd_grub import fix_grub_text, add_iventoy_network_boot
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


    def test_iventoy_http_path_does_not_require_virtual_disk(self):
        cfg = add_iventoy_network_boot(self.NATIVE)
        verify(cfg)
        self.assertIn("Start HAOS via iVentoy HTTP (network root)", cfg)
        self.assertIn("read haos_server", cfg)
        self.assertIn("read haos_image_id", cfg)
        self.assertIn("root=live:http://${haos_server}:16000/eiso/id/${haos_image_id}/LiveOS/squashfs.img", cfg)
        self.assertIn("ip=dhcp rd.neednet=1", cfg)
        self.assertIn("linux /isolinux/vmlinuz0 root=live:LABEL=", cfg)

    def test_no_duplicate_pxe_entry(self):
        with self.assertRaises(ValueError):
            add_iventoy_network_boot(add_iventoy_network_boot(self.NATIVE))

    def test_reject_incompatible_generated_menu(self):
        with self.assertRaises(ValueError):
            verify(self.LEGACY)


if __name__ == "__main__":
    unittest.main()
