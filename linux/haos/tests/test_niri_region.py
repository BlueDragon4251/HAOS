"""Check the actual immutable Herald niri template and regional XKB renderer."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "linux/bin/herald-os"
TEMPLATE = ROOT / "linux/niri/config.kdl"


def renderer():
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_keyboard_layout")
    isolated = ast.Module(body=[fn], type_ignores=[])
    code = compile(isolated, str(SOURCE), "exec")
    namespace = {"REGIONAL_LAYOUTS": ("at", "de", "us", "gb", "fr", "ch")}
    exec(code, namespace)
    return namespace["render_keyboard_layout"]


class RegionalNiriTest(unittest.TestCase):
    def test_austrian_layout_is_included_in_real_template(self):
        original = TEMPLATE.read_text()
        selected = renderer()(original, "at")
        self.assertIn('layout "at"', selected)
        self.assertEqual(selected.count('layout "at"'), 1)
        self.assertIn('include "local.kdl"', selected)
        self.assertNotIn('layout "at"', renderer()(original, None))

    def test_untrusted_keymap_cannot_inject_kdl(self):
        with self.assertRaises(ValueError):
            renderer()(TEMPLATE.read_text(), 'at"; spawn "sh"')

    def test_layout_is_idempotent_only_on_template(self):
        original = TEMPLATE.read_text()
        at = renderer()(original, "at")
        with self.assertRaises(ValueError):
            renderer()(at, "de")


if __name__ == "__main__":
    unittest.main()
