"""Herald OS from the release tarball: herald-os-tarball, and the commands finding their data in /opt/herald-os."""

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "linux" / "bin"


def load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


tb = load("herald_os_tarball", BIN / "herald-os-tarball")
cli = load("herald_os_cli_tarball", BIN / "herald-os")


def asar(manifest: dict) -> bytes:
    """An app.asar holding only package.json, laid out as Electron writes them."""
    body = json.dumps(manifest).encode()
    text = json.dumps({"files": {"package.json": {"size": len(body), "offset": "0"}}}).encode()
    padded = text + b"\0" * (-len(text) % 4)
    header = struct.pack("<II", 4 + len(padded), len(text)) + padded
    return struct.pack("<II", 4, len(header)) + header + body


def write(path: Path, data, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(mode)


def make_app(app: Path, version: str, tools=("herald-os", "herald-os-app", "herald-os-update", "herald-os-tarball")) -> Path:
    """An unpacked release tarball: the Electron binary, app.asar and the Linux resources."""
    write(app / "herald-os", "#!/bin/sh\n", 0o755)
    write(app / "chrome-sandbox", "", 0o755)
    write(app / "resources" / "app.asar", asar({"name": "@herald-os/desktop", "version": version}))
    write(app / "resources" / "icons" / "herald-os.png", b"\x89PNG")
    linux = app / "resources" / "herald-os-linux"
    for tool in tools:
        source = BIN / tool
        write(linux / "bin" / tool, source.read_bytes() if source.exists() else "#!/bin/sh\n", 0o755)
    for name in (*tb.SESSION_SCRIPTS, "herald-os.desktop", *tb.UNITS):
        source = ROOT / "linux" / "session" / name
        write(linux / "session" / name, source.read_bytes(), source.stat().st_mode & 0o777)
    shutil.copytree(ROOT / "linux" / "niri", linux / "niri")
    shutil.copytree(ROOT / "linux" / "catalog", app / "resources" / "catalog")
    shutil.copytree(ROOT / "linux" / "themes", app / "resources" / "themes")
    return app


@pytest.fixture
def layout(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "owner", lambda path: None)
    monkeypatch.setattr(tb.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "niri" else None)
    found = tb.Layout(tmp_path)
    make_app(found.app, "0.1.0")
    return found


def test_the_version_comes_out_of_app_asar(layout, tmp_path):
    assert tb.read_version(layout.app) == "0.1.0"
    write(tmp_path / "broken" / "resources" / "app.asar", b"not an archive")
    assert tb.read_version(tmp_path / "broken") is None
    assert tb.read_version(tmp_path / "missing") is None


def test_versions_sort_the_way_semver_does():
    ordered = ["0.1.0-alpha.1", "0.1.0-alpha.2", "0.1.0-alpha.10", "0.1.0-alpha.beta", "0.1.0-beta", "0.1.0-rc.1", "0.1.0", "0.1.1", "0.2.0", "1.0.0"]
    keys = [tb.version_key(version) for version in ordered]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert tb.is_newer("0.1.0-alpha.2", "0.1.0-alpha.1") and not tb.is_newer("0.1.0-alpha.1", "0.1.0-alpha.1")
    assert not tb.is_newer("0.1.0", "0.2.0-alpha.1")
    assert tb.is_newer("0.1.0", None) and not tb.is_newer("nightly", None)


def release(tag, assets=("x64", "arm64"), prerelease=False, draft=False, checksums=True):
    files = []
    for arch in assets:
        name = f"herald-os-{tag[1:]}-linux-{arch}.tar.gz"
        files.append({"name": name, "size": 1000, "browser_download_url": f"https://example.com/{tag}/{name}"})
        if checksums:
            files.append({"name": f"{name}.sha256", "browser_download_url": f"https://example.com/{tag}/{name}.sha256"})
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": files}


def test_the_newest_stable_release_with_this_machine_s_tarball_wins():
    listing = [
        release("v0.3.0", draft=True),
        release("v0.2.1", assets=("x64",)),
        release("v0.2.0-beta.1", prerelease=True),
        release("v0.1.9", checksums=False),
        release("v0.1.5"),
        release("v0.1.0"),
    ]
    assert tb.pick_release(listing, "x64")["version"] == "0.2.1"
    assert tb.pick_release(listing, "arm64")["version"] == "0.1.5"
    assert tb.pick_release(listing, "arm64", channel="edge")["version"] == "0.2.0-beta.1"
    exact = tb.pick_release(listing, "arm64", version="0.2.0-beta.1")
    assert exact["checksum_url"].endswith("herald-os-0.2.0-beta.1-linux-arm64.tar.gz.sha256")
    assert tb.pick_release(listing, "x64", version="0.3.0") is None
    assert tb.pick_release([], "x64") is None


def test_install_puts_the_session_and_commands_in_place_and_remove_takes_them_out(layout):
    assert tb.install(layout) == 0
    for name in ("herald-os", "herald-os-app", "herald-os-update", "herald-os-tarball", *tb.SESSION_SCRIPTS):
        assert tb.points_into(layout.bin / name, layout.app), name
    assert (layout.bin / "herald-os-compositor").resolve() == (layout.linux / "session" / "herald-os-compositor").resolve()
    assert layout.session_entry == layout.root / "usr" / "share" / "wayland-sessions" / "herald-os.desktop"
    assert "Exec=herald-os-compositor" in layout.session_entry.read_text()
    assert "Exec=herald-os-app" in layout.app_entry.read_text() and layout.icon.read_bytes() == b"\x89PNG"
    assert all((layout.units / unit).is_file() for unit in tb.UNITS)
    assert stat.S_IMODE((layout.app / "chrome-sandbox").stat().st_mode) == 0o4755
    before = outside_opt(layout)
    assert tb.install(layout) == 0
    assert outside_opt(layout) == before
    assert tb.remove(layout) == 0
    assert not [path for path in outside_opt(layout) if path.is_file() or path.is_symlink()]
    assert (layout.app / "resources" / "app.asar").is_file()


def outside_opt(layout) -> list[Path]:
    return sorted(path for path in layout.root.rglob("*") if path.relative_to(layout.root).parts[0] != "opt")


def test_without_niri_the_login_screen_gets_no_session_it_cannot_start(layout, monkeypatch, capsys):
    tb.install(layout)
    monkeypatch.setattr(tb.shutil, "which", lambda name: None)
    tb.install(layout)
    assert not any(entry.exists() for entry in layout.session_entries)
    assert "needs niri" in capsys.readouterr().out
    assert layout.app_entry.is_file()


def test_ostree_systems_get_the_session_under_usr_local(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "owner", lambda path: None)
    monkeypatch.setattr(tb.shutil, "which", lambda name: "/usr/bin/niri")
    write(tmp_path / "run" / "ostree-booted", "")
    found = tb.Layout(tmp_path)
    make_app(found.app, "0.1.0")
    tb.install(found)
    assert (tmp_path / "usr" / "local" / "share" / "wayland-sessions" / "herald-os.desktop").is_file()
    assert not (tmp_path / "usr" / "share").exists()


def test_install_leaves_files_that_are_not_its_links_alone(layout):
    write(layout.bin / "herald-os-app", "#!/bin/sh\necho mine\n", 0o755)
    with pytest.raises(SystemExit):
        tb.install(layout)
    assert (layout.bin / "herald-os-app").read_text() == "#!/bin/sh\necho mine\n"
    assert not (layout.bin / "herald-os").exists()


def test_install_drops_links_to_commands_the_version_no_longer_has(layout):
    tb.install(layout)
    (layout.linux / "bin" / "herald-os-app").unlink()
    tb.install(layout)
    assert not (layout.bin / "herald-os-app").is_symlink()


def test_a_package_s_herald_os_is_left_to_the_package(layout, monkeypatch, capsys):
    monkeypatch.setattr(tb, "owner", lambda path: "herald-os-bin")
    assert "herald-os-bin package" in tb.not_a_tarball(layout)
    assert tb.status(layout) == 2 and tb.check(layout, "stable") == 2
    assert "herald-os-bin" in capsys.readouterr().err
    shutil.rmtree(layout.app)
    assert "no Herald OS release tarball" in tb.not_a_tarball(layout)


def tarball_of(app: Path, version: str, arch: str, out: Path) -> tuple[Path, Path]:
    """A release tarball (one top folder, as electron-builder writes it) and its .sha256."""
    name = f"herald-os-{version}-linux-{arch}.tar.gz"
    with tarfile.open(out / name, "w:gz") as archive:
        archive.add(app, arcname=name[: -len(".tar.gz")])
    checksum = out / f"{name}.sha256"
    checksum.write_text(f"{hashlib.sha256((out / name).read_bytes()).hexdigest()}  {name}\n")
    return out / name, checksum


@pytest.fixture
def published(layout, tmp_path, monkeypatch):
    """Release 0.2.0 on a stand-in for GitHub; downloads copy from it."""
    served = tmp_path / "served"
    served.mkdir()
    arch = tb.machine_arch() or "x64"
    monkeypatch.setattr(tb, "machine_arch", lambda: arch)
    tarball_of(make_app(tmp_path / "build" / "app", "0.2.0"), "0.2.0", arch, served)
    monkeypatch.setattr(tb, "releases", lambda: [release("v0.2.0")])
    monkeypatch.setattr(tb, "download", lambda url, target: shutil.copy(served / url.rsplit("/", 1)[1], target))
    tb.install(layout)
    return served


def test_update_swaps_in_the_new_release_and_rollback_swaps_back(layout, published, capsys):
    assert tb.check(layout, "stable") == 0 and capsys.readouterr().out.strip() == "0.2.0"
    assert tb.update(layout) == 0
    assert tb.read_version(layout.app) == "0.2.0" and tb.read_version(layout.previous) == "0.1.0"
    assert stat.S_IMODE((layout.app / "chrome-sandbox").stat().st_mode) == 0o4755
    assert tb.points_into(layout.bin / "herald-os", layout.app) and (layout.bin / "herald-os").resolve().is_file()
    assert not list(layout.app.parent.glob(".herald-os-update-*"))
    assert tb.check(layout, "stable") == 1
    assert tb.update(layout) == 0 and "up to date" in capsys.readouterr().out
    assert tb.rollback(layout) == 0
    assert tb.read_version(layout.app) == "0.1.0" and tb.read_version(layout.previous) == "0.2.0"


def test_a_tarball_that_does_not_match_its_checksum_changes_nothing(layout, published):
    (published / f"herald-os-0.2.0-linux-{tb.machine_arch()}.tar.gz").write_bytes(b"something else")
    with pytest.raises(SystemExit):
        tb.update(layout)
    assert tb.read_version(layout.app) == "0.1.0" and not layout.previous.exists()
    assert not list(layout.app.parent.glob(".herald-os-update-*"))


def test_a_checksum_file_for_another_file_is_refused(tmp_path):
    tarball = tmp_path / "herald-os-0.2.0-linux-x64.tar.gz"
    tarball.write_bytes(b"data")
    checksum = tmp_path / "sums.sha256"
    checksum.write_text(f"{hashlib.sha256(b'data').hexdigest()}  herald-os-0.2.0-linux-arm64.tar.gz\n")
    with pytest.raises(tb.ReleaseError):
        tb.verify(tarball, checksum)
    checksum.write_text(f"{hashlib.sha256(b'data').hexdigest()}  {tarball.name}\n")
    tb.verify(tarball, checksum)


def test_the_command_line_stages_into_herald_os_destdir(tmp_path):
    make_app(tmp_path / "opt" / "herald-os", "0.1.0")
    env = {**os.environ, "HERALD_OS_DESTDIR": str(tmp_path)}
    tool = tmp_path / "opt" / "herald-os" / "resources" / "herald-os-linux" / "bin" / "herald-os-tarball"
    assert subprocess.run([sys.executable, str(tool), "install"], env=env, capture_output=True, text=True).returncode == 0
    shown = subprocess.run([sys.executable, str(tmp_path / "usr" / "local" / "bin" / "herald-os-tarball"), "status"], env=env, capture_output=True, text=True)
    assert shown.returncode == 0 and "Herald OS 0.1.0, from the release tarball" in shown.stdout
    assert subprocess.run([sys.executable, str(tool), "check", "--channel", "nightly"], env=env, capture_output=True).returncode == 2


def test_the_commands_find_the_catalog_and_themes_in_the_tarball(tmp_path):
    app = make_app(tmp_path / "opt" / "herald-os", "0.1.0", tools=("herald-os", "herald-os-catalog", "herald-os-theme"))
    linked = tmp_path / "usr" / "local" / "bin"
    linked.mkdir(parents=True)
    for tool in ("herald-os", "herald-os-catalog", "herald-os-theme"):
        (linked / tool).symlink_to(app / "resources" / "herald-os-linux" / "bin" / tool)
    env = {"HOME": str(tmp_path / "home"), "PATH": os.pathsep.join([str(linked), str(Path(sys.executable).parent), "/usr/bin", "/bin"])}
    listing = subprocess.run([sys.executable, str(linked / "herald-os-catalog"), "list", "--json"], env=env, capture_output=True, text=True, check=True)
    groups = json.loads(listing.stdout)["groups"]
    assert len(groups) > 5 and all(group["entries"] for group in groups)
    themes = subprocess.run([sys.executable, str(linked / "herald-os-theme"), "list"], env=env, capture_output=True, text=True, check=True)
    assert "herald-ocean" in themes.stdout and "herald-paper" in themes.stdout
    names = subprocess.run([sys.executable, str(linked / "herald-os"), "theme", "list"], env=env, capture_output=True, text=True, check=True)
    assert len(names.stdout.split()) == len(list((ROOT / "linux" / "themes").glob("*/theme.json")))


def test_setup_says_how_to_start_what_is_installed(tmp_path, monkeypatch):
    entry = tmp_path / "herald-os.desktop"
    monkeypatch.setattr(cli, "SESSION_ENTRIES", (entry,))
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/niri")
    assert "sudo herald-os-tarball install" in cli.session_hint()
    entry.write_text("[Desktop Entry]\n")
    assert cli.session_hint().startswith("Start the full session from your login screen")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert "also needs niri" in cli.session_hint()


def updater_env(tmp_path, check_exit: int):
    """herald-os-update with stand-ins for herald-os, sudo and herald-os-tarball (which reports 0.2.0)."""
    stubs, home, repo = tmp_path / "stubs", tmp_path / "home", tmp_path / "checkout"
    for folder in (stubs, home, repo / "linux" / "migrations"):
        folder.mkdir(parents=True)
    scripts = {
        "herald-os": 'echo "$@" >>"$HOME/herald-os.log"',
        "sudo": '[ "$1" = -n ] && shift\nexec "$@"',
        "herald-os-tarball": f'echo "$@" >>"$HOME/tarball.log"\n[ "$1" = check ] && echo 0.2.0 && exit {check_exit}\nexit 0',
    }
    for name, body in scripts.items():
        write(stubs / name, f"#!/bin/sh\n{body}\n", 0o755)
    return {"HOME": str(home), "HERALD_OS_REPO": str(repo), "PATH": os.pathsep.join([str(stubs), "/usr/bin", "/bin"])}


def test_the_updater_reports_and_installs_a_newer_release(tmp_path):
    env = updater_env(tmp_path, check_exit=0)
    checked = subprocess.run(["bash", str(BIN / "herald-os-update"), "--check", "--no-system"], env=env, capture_output=True, text=True, timeout=60)
    assert checked.stdout.strip() == "Herald OS 0.2.0"
    assert json.loads((tmp_path / "home" / ".local" / "state" / "herald-os" / "update-available.json").read_text())["pending"] == 1
    subprocess.run(["bash", str(BIN / "herald-os-update"), "--no-system", "--no-hermes"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert (tmp_path / "home" / "tarball.log").read_text().splitlines()[-1] == "update 0.2.0"


def test_the_updater_leaves_an_up_to_date_tarball_alone(tmp_path):
    env = updater_env(tmp_path, check_exit=1)
    checked = subprocess.run(["bash", str(BIN / "herald-os-update"), "--check", "--no-system"], env=env, capture_output=True, text=True, timeout=60)
    assert checked.stdout.strip() == "up to date"
    subprocess.run(["bash", str(BIN / "herald-os-update"), "--no-system", "--no-hermes"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert "update" not in (tmp_path / "home" / "tarball.log").read_text().split()
