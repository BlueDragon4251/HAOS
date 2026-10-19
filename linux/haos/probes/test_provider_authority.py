"""Real root-file/UID isolation and interrupted configuration, in disposable /run only."""

import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos import provider_setup
from haos.provider_proxy import private_credential


@pytest.fixture
def location():
    assert os.geteuid() == 0, "run the explicit authority probe as root"
    path = Path(tempfile.mkdtemp(prefix="haos-provider-probe-", dir="/run"))
    try:
        yield path
    finally:
        shutil.rmtree(path)


def policy(provider="openai"):
    from haos.provider_policy import ENDPOINTS
    return {"version": 1, "provider": provider, "endpoint": ENDPOINTS[provider],
            "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "codex_responses",
            "requests_per_day": 20, "requests_per_minute": 10}


def test_private_real_credentials_are_not_client_configuration_and_rotation_withdraws_old_capability(location):
    key = secrets.token_urlsafe(48)
    provider_setup.publish(policy(), key, config=location)
    first = json.loads((location / "provider-token").read_text())["token"]
    for name in ("provider-credentials", "provider-token"):
        info = (location / name).stat()
        assert info.st_uid == 0 and info.st_mode & 0o777 == 0o600
    for name in ("provider.json", "provider-client.json"):
        assert key not in (location / name).read_text() and first not in (location / name).read_text()
        assert (location / name).stat().st_uid == 0
    provider_setup.publish(policy(), key, config=location)
    assert first != json.loads((location / "provider-token").read_text())["token"]


def test_other_actual_uid_cannot_read_api_or_oauth_credentials(location):
    provider_setup.publish(policy(), secrets.token_urlsafe(48), config=location)
    # Permit traversal so the test specifically proves file mode enforcement.
    location.chmod(0o755)
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            try:
                private_credential(location / "provider-credentials")
            except PermissionError:
                os._exit(0)
            os._exit(2)
        except BaseException:
            os._exit(3)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0


def test_interrupted_provider_change_removes_authority_before_new_key_can_reach_old_provider(location, monkeypatch):
    provider_setup.publish(policy(), secrets.token_urlsafe(48), config=location)
    original = provider_setup.atomic_json
    def interrupted(path, value, **kwargs):
        if path.name == "provider-client.json":
            raise OSError("deliberate disposable write failure")
        return original(path, value, **kwargs)
    monkeypatch.setattr(provider_setup, "atomic_json", interrupted)
    with pytest.raises(OSError):
        provider_setup.publish(policy("openrouter"), secrets.token_urlsafe(48), config=location)
    assert not (location / "provider.json").exists()


@pytest.mark.parametrize("kind", ["foreign", "writable", "symlink"])
def test_untrusted_owner_configuration_directory_cannot_publish_credentials(location, kind):
    target = location / "config"
    target.mkdir()
    if kind == "foreign":
        os.chown(target, 65534, 65534)
    elif kind == "writable":
        target.chmod(0o777)
    else:
        target.rmdir()
        target.symlink_to(location, target_is_directory=True)
    with pytest.raises(PermissionError):
        provider_setup.publish(policy(), secrets.token_urlsafe(48), config=target)
    assert not (location / "provider-credentials").exists()


@pytest.mark.parametrize("kind", ["symlink", "public", "oversized"])
def test_service_credential_loader_refuses_unsafe_descriptors(location, kind):
    path = location / "secret"
    path.write_text("fixture")
    path.chmod(0o600)
    if kind == "symlink":
        path.rename(location / "target")
        path.symlink_to(location / "target")
    elif kind == "public":
        path.chmod(0o644)
    else:
        path.write_text("x" * 32769)
    with pytest.raises((PermissionError, OSError)):
        private_credential(path)
