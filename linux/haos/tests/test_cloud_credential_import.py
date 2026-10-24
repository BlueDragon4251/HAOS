"""Actual bounded data-file parsing; privileged owner/UID acceptance is separate."""
import json
import os
import secrets

import pytest

from haos import initial_setup, initial_setup_gui


@pytest.fixture
def file_seat(monkeypatch):
    # This ordinary-user fixture exercises data/descriptor handling only.
    # The mandatory real-root authority probe checks the privileged boundary.
    monkeypatch.setattr(initial_setup, "require_root", lambda: None)
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: True)
    monkeypatch.setattr(initial_setup, "owners", lambda: [{"uid": os.getuid()}])


@pytest.mark.parametrize("provider,data", [
    ("bedrock", {"profile": "owner-fixture"}),
    ("azure-foundry", {"tenant_id": "fixture-tenant", "client_id": "fixture-client", "client_secret": "fixture-private-value"}),
    ("vertex", {"type": "authorized_user", "client_id": "fixture-client", "client_secret": "fixture-private-value", "refresh_token": "fixture-private-refresh"}),
])
def test_selected_cloud_json_is_validated_without_changing_the_private_source(file_seat, tmp_path, provider, data):
    path = tmp_path / "private.json"
    original = json.dumps(data).encode()
    path.write_bytes(original)
    path.chmod(0o600)
    assert json.loads(initial_setup.import_cloud_credential(provider, path)) == data
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "oversized", "empty-object", "scalar"])
def test_unsafe_or_empty_file_is_not_imported(file_seat, tmp_path, kind):
    path = tmp_path / "selected.json"
    path.write_text(json.dumps({"bearer_token": secrets.token_urlsafe(40)}))
    path.chmod(0o600)
    if kind == "symlink":
        target = tmp_path / "target.json"
        path.rename(target)
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(path, tmp_path / "other.json")
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "oversized":
        path.write_bytes(b"x" * 16385)
    elif kind == "empty-object":
        path.write_text("{}")
    else:
        path.write_text('"not a credential object"')
    with pytest.raises((PermissionError, ValueError, OSError)):
        initial_setup.import_cloud_credential("bedrock", path)


def test_file_cannot_substitute_a_google_token_endpoint(file_seat, tmp_path):
    path = tmp_path / "private.json"
    path.write_text(json.dumps({"type": "authorized_user", "token_uri": "https://unapproved.invalid/token"}))
    path.chmod(0o600)
    with pytest.raises(PermissionError):
        initial_setup.import_cloud_credential("vertex", path)


def test_nonseat_and_noncloud_choices_fail_before_opening_a_file(file_seat, monkeypatch):
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: False)
    with pytest.raises(PermissionError):
        initial_setup.import_cloud_credential("bedrock", "/no-such-file")
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: True)
    with pytest.raises(PermissionError):
        initial_setup.import_cloud_credential("openai", "/no-such-file")
