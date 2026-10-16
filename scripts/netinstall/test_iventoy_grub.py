"""Regression tests for iVentoy-compatible GRUB generation."""
import unittest
from fix_livecd_grub import fix_source
from verify_live_grub import verify


class IventoyGrubTest(unittest.TestCase):
    def test_patch_exact_efi_template(self):
        source = (
            "menuentry x {\n"
            "  %(tab)slinuxefi /%(imgdir)s/vmlinuz%(index)s root=live\n"
            "  %(tab)sinitrdefi /%(imgdir)s/initrd%(index)s.img\n"
            "}\n"
        )
        changed = fix_source(source)
        self.assertIn("%(tab)slinux /", changed)
        self.assertIn("%(tab)sinitrd /", changed)
        self.assertNotIn("linuxefi", changed)
        self.assertNotIn("initrdefi", changed)

    def test_refuse_changed_upstream_template(self):
        with self.assertRaises(ValueError):
            fix_source("no known grub syntax")

    def test_refuse_multiple_matches(self):
        with self.assertRaises(ValueError):
            fix_source("%(tab)slinuxefi %(tab)slinuxefi %(tab)sinitrdefi ")

    def test_compatible_menu(self):
        verify("menuentry HAOS {\n linux /isolinux/vmlinuz0 root=live\n initrd /isolinux/initrd0.img\n}")

    def test_reject_incompatible_menu(self):
        with self.assertRaisesRegex(ValueError, "linuxefi"):
            verify("linuxefi /isolinux/vmlinuz0\ninitrdefi /isolinux/initrd0.img")

    def test_reject_missing_initrd(self):
        with self.assertRaises(ValueError):
            verify("linux /isolinux/vmlinuz0")


if __name__ == "__main__":
    unittest.main()
