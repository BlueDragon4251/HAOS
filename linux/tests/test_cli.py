"""Pure helpers in the herald-os CLI (linux/bin/herald-os), loaded as a module."""

import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_LOADER = importlib.machinery.SourceFileLoader("herald_os_cli", str(ROOT / "linux" / "bin" / "herald-os"))
_SPEC = importlib.util.spec_from_loader("herald_os_cli", _LOADER)
cli = importlib.util.module_from_spec(_SPEC)
_LOADER.exec_module(cli)

TEMPLATE = (ROOT / "linux" / "niri" / "config.kdl").read_text()


def binds(config: str) -> dict[str, str]:
    """Key -> the rest of the line, for every bind line in the binds block."""
    out: dict[str, str] = {}
    inside = False
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("binds {"):
            inside = True
            continue
        if inside and stripped == "}":
            break
        if inside and stripped and not stripped.startswith("//"):
            key, _, rest = stripped.partition(" ")
            assert key not in out, f"duplicate bind {key}"
            out[key] = rest
    return out


def test_herald_keymap_is_the_template():
    assert cli.render_keymap(TEMPLATE, "herald") == TEMPLATE


def test_template_keys_the_omarchy_keymap_moves_to_are_free():
    keys = binds(TEMPLATE)
    for moved in cli.OMARCHY_MOVES.values():
        assert moved not in keys
    assert "Mod+X" not in keys


def test_omarchy_keymap_rewrites_copy_cut_and_paste():
    keys = binds(cli.render_keymap(TEMPLATE, "omarchy"))
    assert '"-k" "Insert"' in keys["Mod+C"] and '"ctrl"' in keys["Mod+C"]
    assert '"shift" "-k" "Insert"' in keys["Mod+V"]
    assert '"ctrl" "x"' in keys["Mod+X"]
    # Herald's binds are kept, one modifier over.
    assert "center-column" in keys["Mod+Ctrl+C"]
    assert '"herald-os" "voice"' in keys["Mod+Shift+V"]
    # Nothing else changed.
    original = binds(TEMPLATE)
    for key, rest in original.items():
        if key not in ("Mod+C", "Mod+V"):
            assert keys[key] == rest


def test_weather_url_for_a_place_or_the_network():
    assert cli.weather_url("").startswith("https://wttr.in/?format=")
    assert cli.weather_url("New  York").startswith("https://wttr.in/New+York?")
    assert cli.weather_url("~Eiffel Tower").startswith("https://wttr.in/~Eiffel+Tower?")
    # Anything that would change the request is escaped.
    assert cli.weather_url("a/b?c#d").startswith("https://wttr.in/a%2Fb%3Fc%23d?")


def test_unknown_keymap_falls_back_to_herald(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "KEYMAP_FILE", tmp_path / "keymap")
    assert cli.current_keymap() == "herald"
    (tmp_path / "keymap").write_text("vim\n")
    assert cli.current_keymap() == "herald"
    (tmp_path / "keymap").write_text("omarchy\n")
    assert cli.current_keymap() == "omarchy"
