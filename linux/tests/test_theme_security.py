import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("theme_security", str(ROOT / "linux/bin/herald-os-theme"))
spec = importlib.util.spec_from_loader(loader.name, loader)
theme = importlib.util.module_from_spec(spec)
loader.exec_module(theme)
BASE = json.loads((ROOT / "linux/themes/herald-ocean/theme.json").read_text())


def test_builtin_themes_match_the_linux_data_schema():
    for directory in (ROOT / "linux/themes").iterdir():
        if (directory / "theme.json").is_file():
            assert theme.read_spec(directory)["name"] == directory.name


@pytest.mark.parametrize("payload", [
    {"wallpaper": "../../owner.png"}, {"wallpaper": "/etc/shadow"}, {"wallpaper": "active.svg"},
    {"script": "run-me"}, {"label": "\x1b[2J"}, {"shell": {"scheme": "malicious"}},
    {"gtk": {"theme": "Adwaita\n[evil]"}}, {"terminal": {"cursor": "#fff\nfont=evil"}},
])
def test_theme_rejects_path_and_config_injection(payload):
    with pytest.raises(ValueError):
        theme.validate({**copy.deepcopy(BASE), **payload})


def test_theme_asset_and_manifest_symlinks_are_not_followed(tmp_path):
    directory = tmp_path / "herald-ocean"
    directory.mkdir()
    secret = tmp_path / "private.png"
    secret.write_text("owner secret")
    (directory / "wallpaper.png").symlink_to(secret)
    (directory / "theme.json").write_text(json.dumps({**BASE, "wallpaper": "wallpaper.png"}))
    with pytest.raises(ValueError, match="symlink"):
        theme.read_spec(directory)
    (directory / "theme.json").unlink()
    (directory / "theme.json").symlink_to(secret)
    with pytest.raises(OSError):
        theme.read_spec(directory)


def test_invalid_theme_name_cannot_escape_search_base(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "THEME_DIRS", [tmp_path / "themes"])
    assert theme.find("../private") is None
