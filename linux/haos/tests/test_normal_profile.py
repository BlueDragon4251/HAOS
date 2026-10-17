import os
from types import SimpleNamespace
from pathlib import Path
import pytest

from haos import normal_profile


def test_non_root_cannot_control_locked_observer(monkeypatch):
    monkeypatch.setattr(normal_profile.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        normal_profile.configure_name("Me")
    with pytest.raises(PermissionError):
        normal_profile.name_exists()
    with pytest.raises(PermissionError):
        normal_profile.mark_ready()


def test_fixed_observer_identity_is_not_attacker_selectable(monkeypatch):
    monkeypatch.setattr(normal_profile.os, "geteuid", lambda: 0)
    monkeypatch.setattr(normal_profile.pwd, "getpwnam",
                        lambda who: SimpleNamespace(pw_uid=0, pw_gid=0, pw_dir="/root"))
    with pytest.raises(PermissionError):
        normal_profile.configure_name("A")


def test_region_validation_before_untrusted_path_write(monkeypatch):
    monkeypatch.setattr(normal_profile, "_observer",
                        lambda: SimpleNamespace(pw_uid=1001, pw_gid=1001))
    with pytest.raises(ValueError):
        normal_profile.configure_region("incorrect", "at")
    with pytest.raises(ValueError):
        normal_profile.configure_region("de_AT.UTF-8", "XWAYLAND")


def test_display_name_bounded(monkeypatch):
    monkeypatch.setattr(normal_profile, "_observer",
                        lambda: SimpleNamespace(pw_uid=1001, pw_gid=1001))
    for name in ("", "bad\nline", "X" * 80, "\u007f"):
        with pytest.raises(ValueError):
            normal_profile.configure_name(name)


def test_no_symlink_or_world_writable_config_can_be_replaced(tmp_path, monkeypatch):
    fake = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    monkeypatch.setattr(normal_profile, "HOME", tmp_path)
    target = tmp_path / ".config"
    target.symlink_to(tmp_path)
    with pytest.raises(PermissionError):
        normal_profile._directory(target, fake)
    target.unlink()
    target.mkdir(mode=0o777)
    target.chmod(0o777)
    with pytest.raises(PermissionError):
        normal_profile._directory(target, fake)


def test_existing_user_data_preserved_when_marking_ready(tmp_path, monkeypatch):
    fake = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    monkeypatch.setattr(normal_profile, "HOME", tmp_path)
    monkeypatch.setattr(normal_profile, "_observer", lambda: fake)
    (tmp_path / ".config").mkdir(mode=0o700)
    (tmp_path / ".config/herald-os").mkdir(mode=0o700)
    (tmp_path / ".config/herald-os/name").write_text("Existing person\n")
    assert normal_profile.name_exists()
    old = tmp_path / ".config/herald-os/setup-done"
    old.write_text("keep existing contents")
    normal_profile.mark_ready()
    assert old.read_text() == "keep existing contents"
