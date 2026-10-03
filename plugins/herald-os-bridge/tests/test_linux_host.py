"""Contracts for the pure Linux parsers and the ``.desktop`` scanner (no Linux tools are executed)."""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge.host." + name)


SS_OUTPUT = """Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
tcp   LISTEN 0      511          0.0.0.0:3000       0.0.0.0:*    users:(("node",pid=512,fd=23))
tcp   LISTEN 0      511             [::]:3000          [::]:*    users:(("node",pid=512,fd=24))
tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*    users:(("sshd",pid=800,fd=3))
udp   UNCONN 0      0            0.0.0.0:3000       0.0.0.0:*    users:(("chromium",pid=900,fd=41))
tcp   LISTEN 0      4096       127.0.0.1:631        0.0.0.0:*
"""


def test_parse_ss_one_row_per_pid_with_protocol(plugin):
    linux = _mod(plugin, "linux")
    rows = linux.parse_ss(SS_OUTPUT, 3000)
    assert [(r.pid, r.command, r.protocol) for r in rows] == [(512, "node", "tcp"), (900, "chromium", "udp")]
    assert all(r.port == 3000 for r in rows)
    assert linux.parse_ss(SS_OUTPUT, 22)[0].command == "sshd"
    assert linux.parse_ss(SS_OUTPUT, 8080) == []


def test_parse_ss_without_netid_column_and_without_owner(plugin):
    linux = _mod(plugin, "linux")
    text = "State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\nLISTEN 0      4096   *:8080            *:*     users:((\"java\",pid=42,fd=9))\nLISTEN 0      128    127.0.0.1:631     0.0.0.0:*\n"
    rows = linux.parse_ss(text, 8080)
    assert rows[0].pid == 42 and rows[0].protocol == "tcp"
    hidden = linux.parse_ss(text, 631)
    assert hidden[0].pid == 0 and "unknown" in hidden[0].command, "a listener we cannot inspect is still reported"


def test_parse_nmcli_dev_status_handles_escaped_colons(plugin):
    linux = _mod(plugin, "linux")
    rows = linux.parse_nmcli_dev_status("wifi:connected:Home\\:Net:wlp3s0\nethernet:unavailable::enp0s31f6\nloopback:connected (externally):lo:lo\n")
    assert rows[0] == {"type": "wifi", "state": "connected", "connection": "Home:Net", "device": "wlp3s0"}
    assert rows[1]["connection"] == "" and rows[1]["device"] == "enp0s31f6"
    assert rows[2]["type"] == "loopback"


def test_parse_nmcli_wifi_marks_active_network(plugin):
    linux = _mod(plugin, "linux")
    nets = linux.parse_nmcli_wifi("yes:HomeNet:78:44:540 Mbit/s:WPA2\nno:Cafe\\:Free:40:6:130 Mbit/s:\nno::12:1:54 Mbit/s:WPA1 WPA2\n")
    assert nets[0] == {"active": True, "ssid": "HomeNet", "signal": 78, "channel": "44", "rate": "540 Mbit/s", "security": "WPA2"}
    assert nets[1]["ssid"] == "Cafe:Free" and nets[1]["active"] is False and nets[1]["security"] is None
    assert nets[2]["ssid"] is None, "hidden networks have an empty SSID"
    minimal = linux.parse_nmcli_wifi("yes:Office:55\n")
    assert minimal == [{"active": True, "ssid": "Office", "signal": 55}]


def test_parse_ip_route_and_addr(plugin):
    linux = _mod(plugin, "linux")
    assert linux.parse_ip_route('[{"dst":"default","gateway":"192.168.1.1","dev":"wlp3s0","protocol":"dhcp","metric":600}]') == ("192.168.1.1", "wlp3s0")
    assert linux.parse_ip_route("") == (None, None)
    addrs = linux.parse_ip_addr('[{"ifname":"lo","flags":["LOOPBACK","UP"],"address":"00:00:00:00:00:00","addr_info":[{"family":"inet","local":"127.0.0.1"}]},'
                                '{"ifname":"wlp3s0","flags":["BROADCAST","UP"],"address":"aa:bb:cc:dd:ee:ff","addr_info":[{"family":"inet6","local":"fe80::1"},{"family":"inet","local":"192.168.1.20"}]}]')
    assert addrs["wlp3s0"] == {"mac": "aa:bb:cc:dd:ee:ff", "ipv4": "192.168.1.20", "up": True}


def test_parse_wpctl_and_pactl_volume(plugin):
    linux = _mod(plugin, "linux")
    assert linux.parse_wpctl_volume("Volume: 0.45 [MUTED]\n") == (45, True)
    assert linux.parse_wpctl_volume("Volume: 1.00\n") == (100, False)
    assert linux.parse_wpctl_volume("") == (None, False)
    assert linux.parse_pactl_volume("Volume: front-left: 29491 /  45% / -20.83 dB,   front-right: 29491 /  45% / -20.83 dB") == 45


def test_parse_bluetoothctl(plugin):
    linux = _mod(plugin, "linux")
    show = "Controller AA:BB:CC:DD:EE:FF thinkpad [default]\n\tName: thinkpad\n\tAlias: thinkpad\n\tPowered: yes\n\tDiscoverable: no\n"
    assert linux.parse_bluetoothctl_show(show) == {"powered_on": True, "name": "thinkpad", "address": "AA:BB:CC:DD:EE:FF"}
    assert linux.parse_bluetoothctl_show("No default controller available\n")["powered_on"] is None
    assert linux.parse_bluetoothctl_devices("Device 11:22:33:44:55:66 AirPods Pro\nDevice 77:88:99:AA:BB:CC MX Master 3\n") == ["AirPods Pro", "MX Master 3"]


def test_parse_os_release_meminfo_cpuinfo(plugin):
    linux = _mod(plugin, "linux")
    release = linux.parse_os_release('PRETTY_NAME="Ubuntu 24.04.1 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n# comment\n')
    assert release["PRETTY_NAME"] == "Ubuntu 24.04.1 LTS" and release["VERSION_ID"] == "24.04" and release["ID"] == "ubuntu"
    mem = linux.parse_meminfo("MemTotal:       16384000 kB\nMemFree:         1024000 kB\nMemAvailable:    8192000 kB\nHugePages_Total:       0\n")
    assert mem["MemTotal"] == 16384000 * 1024 and mem["HugePages_Total"] == 0
    assert linux.parse_cpuinfo_model("processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: Intel(R) Core(TM) i7-1165G7 @ 2.80GHz\n") == "Intel(R) Core(TM) i7-1165G7 @ 2.80GHz"
    assert linux.parse_cpuinfo_model("processor\t: 0\nModel\t\t: Raspberry Pi 5 Model B Rev 1.0\n") == "Raspberry Pi 5 Model B Rev 1.0"


def test_parse_df_keeps_real_volumes_only(plugin):
    linux = _mod(plugin, "linux")
    text = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "/dev/nvme0n1p2 500000000 250000000 250000000 50% /\n"
            "/dev/nvme0n1p1 500000 100000 400000 20% /boot/efi\n"
            "/dev/sdb1 2000000000 1000000000 1000000000 50% /run/media/sam/Backup\n"
            "/dev/loop3 100000 100000 0 100% /snap/core/1\n")
    disks = linux.parse_df(text)
    assert [d["mount"] for d in disks] == ["/", "/run/media/sam/Backup"]
    assert disks[0]["total_bytes"] == 500000000 * 1024


def test_parse_gsettings_value_strips_gvariant_quotes(plugin):
    linux = _mod(plugin, "linux")
    assert linux.parse_gsettings_value("'prefer-dark'\n") == "prefer-dark"
    assert linux.parse_gsettings_value("'Yaru-dark'") == "Yaru-dark"


def test_matches_search_honours_kind_extensions_scope_and_dates(plugin, tmp_path):
    linux = _mod(plugin, "linux")
    base = _mod(plugin, "base")
    shot = str(tmp_path / "Pictures" / "Screenshot from 2026-09-16 10-00-00.png")
    ts = datetime(2026, 9, 16, 10, 0).timestamp()
    query = base.FileSearch(kind="screenshot", since="2026-09-16", until="2026-09-16")
    assert linux.matches_search(shot, query, is_dir=False, mtime=ts)
    assert not linux.matches_search(shot, query, is_dir=False, mtime=datetime(2026, 9, 17, 0, 0).timestamp()), "until is an exclusive end of day"
    assert not linux.matches_search(str(tmp_path / "Pictures" / "holiday.png"), query, is_dir=False, mtime=ts), "screenshots need a screenshot-like name"
    assert linux.matches_search("/home/u/notes/tax return.PDF", base.FileSearch(kind="pdf", text="tax"), is_dir=False, mtime=None)
    assert not linux.matches_search("/home/u/notes/tax.txt", base.FileSearch(kind="pdf", text="tax"), is_dir=False, mtime=None)
    assert linux.matches_search("/home/u/Projects/herald", base.FileSearch(kind="folder", name="herald"), is_dir=True, mtime=None)
    assert not linux.matches_search("/home/u/Projects/herald", base.FileSearch(kind="image"), is_dir=True, mtime=None)
    assert not linux.matches_search("/home/u/Downloads/a.png", base.FileSearch(kind="image", scope="/home/u/Pictures"), is_dir=False, mtime=None)
    assert linux.search_extensions(base.FileSearch(kind="image", extensions=("PNG", ".jpg", "mp4"))) == {"png", "jpg"}
    with pytest.raises(ValueError):
        linux.search_time_bounds(base.FileSearch(since="yesterday"))


def test_log_priorities_and_settings_panes_mirror_darwin(plugin):
    linux = _mod(plugin, "linux")
    darwin = _mod(plugin, "darwin")
    assert linux.LOG_PRIORITIES == {"error": "err", "fault": "crit", "any": None}
    for pane in ("privacy_and_security", "wifi", "bluetooth", "sound", "displays", "notifications", "screen_recording"):
        assert pane in linux.SETTINGS_PANES and pane in darwin.SETTINGS_PANES


def test_linux_host_is_unavailable_off_linux(plugin, monkeypatch):
    linux = _mod(plugin, "linux")
    host = linux.LinuxHost()
    monkeypatch.setattr(linux.sys, "platform", "darwin")
    assert host.available() is False
    monkeypatch.setattr(linux.sys, "platform", "linux")
    assert host.available() is True


def test_sleep_display_powers_off_monitors_through_niri(plugin, monkeypatch):
    linux = _mod(plugin, "linux")
    base = _mod(plugin, "base")
    util = importlib.import_module(plugin.__name__ + ".bridge.util")
    calls = []
    monkeypatch.setattr(linux, "run", lambda argv, **kw: calls.append(list(argv)) or util.ExecResult(0, "", ""))
    linux.LinuxHost().sleep_display()
    assert calls == [["niri", "msg", "action", "power-off-monitors"]]
    monkeypatch.setattr(linux, "run", lambda argv, **kw: util.ExecResult(127, "", "niri: not found (No such file)"))
    with pytest.raises(base.HostNotSupported, match="niri"):
        linux.LinuxHost().sleep_display()


def test_missing_binary_becomes_host_not_supported(plugin, monkeypatch):
    linux = _mod(plugin, "linux")
    base = _mod(plugin, "base")
    util = importlib.import_module(plugin.__name__ + ".bridge.util")
    monkeypatch.setattr(linux, "run", lambda argv, **kw: util.ExecResult(127, "", f"{argv[0]}: not found (No such file)"))
    with pytest.raises(base.HostNotSupported, match="bluez"):
        linux.LinuxHost().bluetooth_status()
    with pytest.raises(base.HostNotSupported, match="network-manager"):
        linux.LinuxHost().set_wifi_power(True)


FIREFOX_DESKTOP = """[Desktop Entry]
Version=1.0
Name=Firefox Web Browser
Name[pt]=Navegador Web Firefox
GenericName=Web Browser
Comment=Browse the World Wide Web
Exec=firefox %u
Icon=firefox
Terminal=false
Type=Application
Categories=GNOME;GTK;Network;WebBrowser;
StartupWMClass=firefox
Actions=new-window;

[Desktop Action new-window]
Name=Open a New Window
Exec=firefox -new-window
"""


def test_parse_desktop_entry_strips_exec_codes_and_reads_fields(plugin):
    de = _mod(plugin, "desktop_entries")
    entry = de.parse_desktop_entry(FIREFOX_DESKTOP, "/usr/share/applications/firefox.desktop")
    assert entry is not None
    assert entry.name == "Firefox Web Browser" and entry.exec_cmd == "firefox" and entry.icon == "firefox"
    assert entry.categories == ["GNOME", "GTK", "Network", "WebBrowser"]
    assert entry.startup_wm_class == "firefox" and entry.desktop_id == "firefox" and entry.terminal is False
    assert not entry.no_display and not entry.hidden
    assert de.strip_exec_codes('code --new-window %F --title "100%% done" %i %c') == 'code --new-window --title "100% done"'
    assert de.strip_exec_codes("/usr/bin/flatpak run --branch=stable --file-forwarding org.gimp.GIMP @@u %U @@") == "/usr/bin/flatpak run --branch=stable --file-forwarding org.gimp.GIMP @@u @@"


def test_parse_desktop_entry_rejects_non_apps_and_flags_hidden(plugin):
    de = _mod(plugin, "desktop_entries")
    assert de.parse_desktop_entry("[Desktop Entry]\nType=Link\nName=Docs\nURL=https://x\n", "/tmp/docs.desktop") is None
    assert de.parse_desktop_entry("[Desktop Entry]\nType=Application\nName=NoExec\n", "/tmp/noexec.desktop") is None
    assert de.parse_desktop_entry("[Other Group]\nName=x\nExec=y\n", "/tmp/other.desktop") is None
    hidden = de.parse_desktop_entry("[Desktop Entry]\nType=Application\nName=Helper\nExec=helper\nNoDisplay=true\nOnlyShowIn=KDE;\n", "/tmp/helper.desktop")
    assert hidden is not None and hidden.no_display is True and hidden.only_show_in == ["KDE"]
    assert not de.entry_is_visible(hidden, desktops=["gnome"])
    kde_only = de.parse_desktop_entry("[Desktop Entry]\nType=Application\nName=KDE Thing\nExec=kthing\nOnlyShowIn=KDE;\n", "/tmp/kthing.desktop")
    assert de.entry_is_visible(kde_only, desktops=[]) is True, "unknown desktop: keep the entry"
    assert de.entry_is_visible(kde_only, desktops=["GNOME"]) is False
    assert de.entry_is_visible(kde_only, desktops=["kde"]) is True


def test_process_names_see_through_wrappers(plugin):
    de = _mod(plugin, "desktop_entries")
    env = de.parse_desktop_entry("[Desktop Entry]\nType=Application\nName=Code\nExec=env GDK_BACKEND=x11 /usr/share/code/code --unity-launch %F\nStartupWMClass=Code\n", "/usr/share/applications/code.desktop")
    assert env.process_names() == {"code"}
    flatpak = de.parse_desktop_entry("[Desktop Entry]\nType=Application\nName=Spotify\nExec=/usr/bin/flatpak run --command=spotify com.spotify.Client %U\n", "/var/lib/flatpak/exports/share/applications/com.spotify.Client.desktop")
    assert flatpak.process_names() == {"spotify"} and flatpak.desktop_id == "com.spotify.Client"


def test_scan_desktop_entries_prefers_user_dir_and_skips_hidden(plugin, tmp_path):
    de = _mod(plugin, "desktop_entries")
    system = tmp_path / "usr" / "share" / "applications"
    user = tmp_path / "home" / "applications"
    system.mkdir(parents=True)
    user.mkdir(parents=True)
    (system / "firefox.desktop").write_text(FIREFOX_DESKTOP)
    (system / "org.gnome.Terminal.desktop").write_text("[Desktop Entry]\nType=Application\nName=Terminal\nExec=gnome-terminal\nCategories=System;TerminalEmulator;\n")
    (system / "hidden-helper.desktop").write_text("[Desktop Entry]\nType=Application\nName=Helper\nExec=helper\nNoDisplay=true\n")
    (system / "mimeinfo.cache").write_text("[MIME Cache]\n")
    (user / "firefox.desktop").write_text(FIREFOX_DESKTOP.replace("Name=Firefox Web Browser", "Name=Firefox (Developer)"))
    entries = de.scan_desktop_entries([str(user), str(system), str(tmp_path / "missing")], desktops=["gnome"])
    assert [e.name for e in entries] == ["Firefox (Developer)", "Terminal"]
    assert entries[0].path == str(user / "firefox.desktop"), "the user's override wins over the system entry"
    everything = de.scan_desktop_entries([str(system)], include_hidden=True, desktops=["gnome"])
    assert [e.desktop_id for e in everything] == ["firefox", "hidden-helper", "org.gnome.Terminal"]


def test_installed_and_running_apps_map_desktop_entries(plugin, tmp_path, monkeypatch):
    linux = _mod(plugin, "linux")
    de = _mod(plugin, "desktop_entries")
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    (apps_dir / "firefox.desktop").write_text(FIREFOX_DESKTOP)
    (apps_dir / "code.desktop").write_text("[Desktop Entry]\nType=Application\nName=Visual Studio Code\nExec=/usr/share/code/code --unity-launch %F\nStartupWMClass=Code\n")
    host = linux.LinuxHost()
    monkeypatch.setattr(host, "_entries", lambda: de.scan_desktop_entries([str(apps_dir)], desktops=[]))
    monkeypatch.setattr(host, "_ps", lambda: linux.parse_ps("  512   1 sam  12.5  0.3  204800 firefox\n 999 512 sam 0.0 0.0 1024 zsh\n"))
    installed = host.installed_apps()
    assert [(a.name, a.bundle_id) for a in installed] == [("Firefox Web Browser", "firefox"), ("Visual Studio Code", "code")]
    assert installed[0].path == str(apps_dir / "firefox.desktop")
    running = host.running_apps()
    assert [(a.name, a.pid, a.running) for a in running] == [("Firefox Web Browser", 512, True)]
    assert host.resolve_app("code").bundle_id == "code"
    assert host.resolve_app("FIREFOX").name == "Firefox Web Browser"
    assert host.resolve_app("studio").name == "Visual Studio Code"
    assert host.resolve_app("nothing-here") is None
