"""Pure helpers in the herald-os CLI (linux/bin/herald-os), loaded as a module."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

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


def test_wm_maps_niri_actions_to_hyprland_dispatchers(monkeypatch):
    calls = []
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    monkeypatch.delenv("NIRI_SOCKET", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "call", lambda argv: calls.append(argv) or 0)
    cli.wm("close-window")
    cli.wm("focus-workspace", "work")
    cli.wm("focus-workspace", "3")
    cli.wm("exec", "kitty")
    assert calls == [
        ["hyprctl", "dispatch", "killactive"],
        ["hyprctl", "dispatch", "workspace", "name:work"],
        ["hyprctl", "dispatch", "workspace", "3"],
        ["hyprctl", "dispatch", "exec", "kitty"],
    ]


def test_wm_uses_niri_under_niri(monkeypatch):
    calls = []
    monkeypatch.setenv("NIRI_SOCKET", "/run/niri.sock")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "call", lambda argv: calls.append(argv) or 0)
    cli.wm("close-window")
    assert calls == [["niri", "msg", "action", "close-window"]]


def omarchy_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local" / "share" / "omarchy").mkdir(parents=True)
    (home / ".config" / "hypr").mkdir(parents=True)
    (home / ".config" / "hypr" / "hyprland.conf").write_text("source = ~/.local/share/omarchy/default/hypr/bindings.conf\n")
    for name, value in {
        "OMARCHY_SHARE": home / ".local" / "share" / "omarchy",
        "OMARCHY_HOOKS": home / ".config" / "omarchy" / "hooks",
        "OMARCHY_MENU": home / ".config" / "omarchy" / "extensions" / "omarchy-menu.jsonc",
        "HYPR_DIR": home / ".config" / "hypr",
        "HERALD_HYPR": home / ".config" / "hypr" / "herald-os.conf",
        "APP_DESKTOP": home / ".local" / "share" / "applications" / "herald-os-app.desktop",
        "APPS_DIR": home / ".local" / "share" / "applications",
    }.items():
        monkeypatch.setattr(cli, name, value)
    monkeypatch.setattr(cli, "relay", lambda *args, **kwargs: {"ok": True})
    return home


def test_omarchy_install_and_remove_leave_things_as_they_were(tmp_path, monkeypatch, capsys):
    home = omarchy_home(tmp_path, monkeypatch)
    hyprland = home / ".config" / "hypr" / "hyprland.conf"
    before = hyprland.read_text()
    assert cli.omarchy_install() == 0
    assert all(cli.omarchy_status().values())
    hook = home / ".config" / "omarchy" / "hooks" / "theme-set.d" / "herald-os"
    assert hook.stat().st_mode & 0o111 and "herald-os theme omarchy" in hook.read_text()
    assert cli.HYPR_SOURCE in hyprland.read_text()
    binds = (home / ".config" / "hypr" / "herald-os.conf").read_text()
    assert "bindd = SUPER ALT, H, Herald OS keys, submap, herald" in binds and binds.rstrip().endswith("submap = reset")
    # Installing twice adds nothing twice.
    cli.omarchy_install()
    assert hyprland.read_text().count(cli.HYPR_SOURCE) == 1
    assert cli.omarchy_remove() == 0
    assert not any(cli.omarchy_status().values())
    assert hyprland.read_text() == before


def test_omarchy_install_never_overwrites_the_persons_files(tmp_path, monkeypatch, capsys):
    home = omarchy_home(tmp_path, monkeypatch)
    hook = home / ".config" / "omarchy" / "hooks" / "theme-set"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nnotify-send theme \"$1\"\n")
    menu = home / ".config" / "omarchy" / "extensions" / "omarchy-menu.jsonc"
    menu.parent.mkdir(parents=True)
    menu.write_text("[ { \"label\": \"Mine\" } ]\n")
    cli.omarchy_install()
    out = capsys.readouterr().out
    assert hook.read_text() == "#!/bin/sh\nnotify-send theme \"$1\"\n" and "theme-set.d" in out
    assert menu.read_text() == "[ { \"label\": \"Mine\" } ]\n" and '"id": "herald-os"' in out
    cli.omarchy_remove()
    assert hook.exists() and menu.exists()


def test_setup_links_the_bridge_and_enables_it(tmp_path, monkeypatch, capsys):
    bridge = tmp_path / "share" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "plugin.yaml").write_text("name: herald-os-bridge\n")
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setattr(cli, "BRIDGE_DIRS", [tmp_path / "missing", bridge])
    monkeypatch.setattr(cli, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(cli, "hermes_command", lambda: ["/usr/bin/hermes"])
    monkeypatch.setattr(cli, "is_omarchy", lambda: False)
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kwargs: ran.append(argv))
    assert cli.setup([]) == 0
    link = hermes_home / "plugins" / "herald-os-bridge"
    assert link.is_symlink() and link.resolve() == bridge.resolve()
    assert ["/usr/bin/hermes", "plugins", "enable", "herald-os-bridge"] in ran
    assert ["/usr/bin/hermes", "tools", "enable", "herald_os"] in ran
    # Running it again replaces its own link.
    assert cli.setup([]) == 0 and link.is_symlink()


def test_setup_leaves_a_foreign_plugin_folder_alone(tmp_path, monkeypatch):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "plugin.yaml").write_text("name: herald-os-bridge\n")
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "plugins" / "herald-os-bridge").mkdir(parents=True)
    monkeypatch.setattr(cli, "BRIDGE_DIRS", [bridge])
    monkeypatch.setattr(cli, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(cli, "hermes_command", lambda: ["/usr/bin/hermes"])
    with pytest.raises(SystemExit):
        cli.setup([])
    assert (hermes_home / "plugins" / "herald-os-bridge").is_dir()


def test_unknown_keymap_falls_back_to_herald(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "KEYMAP_FILE", tmp_path / "keymap")
    assert cli.current_keymap() == "herald"
    (tmp_path / "keymap").write_text("vim\n")
    assert cli.current_keymap() == "herald"
    (tmp_path / "keymap").write_text("omarchy\n")
    assert cli.current_keymap() == "omarchy"


def test_bar_words_become_registry_commands():
    assert cli.bar_args([]) == ("bar.layout", {})
    assert cli.bar_args(["hide", "bluetooth"]) == ("bar.hide", {"item": "bluetooth"})
    assert cli.bar_args(["move", "clock", "first"]) == ("bar.move", {"item": "clock", "position": "first"})
    assert cli.bar_args(["move", "clock", "3"]) == ("bar.move", {"item": "clock", "position": "3"})
    assert cli.bar_args(["move", "battery", "after", "wifi"]) == ("bar.move", {"item": "battery", "after": "wifi"})
    assert cli.bar_args(["clock", "24h", "seconds", "date", "none"]) == ("bar.clock", {"hours": "24", "seconds": True, "date": "none"})
    assert cli.bar_args(["clock", "System", "no-seconds"]) == ("bar.clock", {"hours": "system", "seconds": False})
    assert cli.bar_args(["reset"]) == ("bar.reset", {})
    for bad in (["move", "clock"], ["move", "clock", "middle"], ["clock"], ["clock", "25h"], ["hide"], ["reset", "now"], ["paint"]):
        with pytest.raises(SystemExit) as stopped:
            cli.bar_args(bad)
        assert stopped.value.code == 2, bad


def test_lock_draws_the_branded_picture_behind_the_ring(tmp_path):
    cfg, image = tmp_path / "config", tmp_path / "lock.jpg"
    assert cli.lock_command(cfg, None) == ["swaylock", "-f", "-C", str(cfg)]
    assert cli.lock_command(None, image) == ["swaylock", "-f", "--color", "04113f", "--image", str(image), "--scaling", "fill"]


def test_branding_lock_image_stays_inside_the_branding_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "BRANDING_DIR", tmp_path)
    assert cli.branding_lock_image() is None
    (tmp_path / "lock.png").write_bytes(b"png")
    (tmp_path / "branding.json").write_text('{"lock": "lock.png"}')
    assert cli.branding_lock_image() == tmp_path / "lock.png"
    (tmp_path / "branding.json").write_text('{"lock": "../lock.png"}')
    assert cli.branding_lock_image() is None


def test_branding_set_makes_paths_absolute(tmp_path):
    patch = cli.branding_patch(["--logo", "art/logo.svg", "--name", "Acme Corp", "--lock", "/srv/beach.jpg"], tmp_path)
    assert patch == {"logo": str((tmp_path / "art" / "logo.svg").resolve()), "name": "Acme Corp", "lock": str(Path("/srv/beach.jpg").resolve())}
    for bad in ([], ["--logo"], ["--colour", "red"], ["logo.png"]):
        with pytest.raises(SystemExit) as stopped:
            cli.branding_patch(bad, tmp_path)
        assert stopped.value.code == 2, bad


class _Stdin:
    def __init__(self, tty: bool):
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_plugin_enable_asks_the_person_and_never_runs_unattended(monkeypatch, capsys):
    sent = []
    listing = {"ok": True, "plugins": [{"id": "weather-strip", "name": "Weather strip", "errors": [], "grants": ["Connect to api.open-meteo.com"]}]}
    monkeypatch.setattr(cli, "relay", lambda cmd, args, *rest, **kwargs: sent.append(args) or (listing if args == ["list"] else {"ok": True}))
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(False))
    with pytest.raises(SystemExit) as stopped:
        cli.plugin_cmd(["enable", "weather-strip"])
    assert stopped.value.code == 2 and sent == [["list"]]
    # At a terminal it lists what the plugin may do, and turns it on only after a yes.
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(True))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert cli.plugin_cmd(["enable", "weather-strip"]) == 1
    assert ["enable", "weather-strip"] not in sent
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.plugin_cmd(["enable", "weather-strip"]) == 0
    assert sent[-1] == ["enable", "weather-strip"]
    assert "Connect to api.open-meteo.com" in capsys.readouterr().out


def test_plugin_add_waits_for_the_clone_and_says_it_is_off(monkeypatch, capsys):
    calls = []
    reply = {"ok": True, "plugin": {"id": "weather-strip", "name": "Weather strip", "version": "1.0.0"}}
    monkeypatch.setattr(cli, "relay", lambda cmd, args, *rest, **kwargs: calls.append((cmd, args, kwargs.get("timeout"))) or reply)
    assert cli.plugin_cmd(["add", "https://example.com/weather-strip.git"]) == 0
    assert calls == [("plugin", ["add", "https://example.com/weather-strip.git"], 180)]
    assert "turned off (herald-os plugin enable weather-strip)" in capsys.readouterr().out
    with pytest.raises(SystemExit) as stopped:
        cli.plugin_cmd(["remove"])
    assert stopped.value.code == 2
