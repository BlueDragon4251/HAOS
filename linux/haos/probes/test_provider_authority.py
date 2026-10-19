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


def test_acp_actual_socket_activation_peer_uids_private_credentials_and_immediate_revocation(location, monkeypatch):
    """Real kernel IPC/UID boundary; model result is explicitly a fixture."""
    import socket
    from types import SimpleNamespace
    from haos import provider_acp
    from haos import provider_native  # Import trusted code before dropping UID.
    location.chmod(0o755)
    endpoint = location / "control.sock"
    broker_key, acp_key = location / "broker-secret", location / "acp-secret"
    for path, uid in ((broker_key, 65534), (acp_key, 65533)):
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
        os.chown(path, uid, uid)
    value = {**policy("copilot-acp"), "api_mode": "chat_completions"}
    config = location / "provider.json"
    config.write_text(json.dumps(value))
    config.chmod(0o644)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(endpoint))
    os.chown(endpoint, 0, 65534)
    endpoint.chmod(0o660)
    listener.listen(4)
    listener.settimeout(10)
    monkeypatch.setattr(provider_acp, "SOCKET", str(endpoint))
    def drop(uid):
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    def denied_read(path):
        try:
            path.read_text()
        except PermissionError:
            return
        raise AssertionError("another actual UID read private provider credentials")
    worker = os.fork()
    if worker == 0:
        try:
            drop(65533)
            denied_read(broker_key)
            def factory():
                return SimpleNamespace(close=lambda: None, chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: {
                    "choices": [{"message": {"content": "fixture-only", "tool_calls": []}, "finish_reason": "stop"}],
                    "model": "fixture-model"})))
            for _ in range(3):
                peer, _ = listener.accept()
                with peer:
                    try:
                        provider_acp.handle(peer, 65534, config=config, factory=factory)
                    except (PermissionError, ValueError):
                        pass
            os._exit(0)
        except BaseException:
            os._exit(3)
    def child(uid, *, allowed=False, kernel_denied=False):
        pid = os.fork()
        if pid == 0:
            try:
                drop(uid)
                if uid == 65534:
                    denied_read(acp_key)
                client = provider_acp.ACPClient(SimpleNamespace(data=value))
                try:
                    result = client.create(model="fixture-model", messages=[{"role": "user", "content": "fixture"}])
                except PermissionError:
                    assert kernel_denied
                except (ValueError, ConnectionError):
                    assert not allowed and not kernel_denied
                else:
                    assert allowed and result["choices"][0]["message"]["content"] == "fixture-only"
                finally:
                    client.close()
                os._exit(0)
            except BaseException:
                os._exit(3)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    worker_done = False
    try:
        # A world-unprivileged identity is denied by the actual socket mode.
        child(65532, kernel_denied=True)
        # Root can bypass socket mode but cannot pass broker peer admission.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.connect(str(endpoint))
            peer.settimeout(5)
            assert peer.recv(1) == b""
        child(65534, allowed=True)
        # Same broker capability does not retain a removed route in the worker.
        config.write_text(json.dumps({**value, "models": ["other"], "default_model": "other"}))
        child(65534)
        _, status = os.waitpid(worker, 0)
        worker_done = True
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        listener.close()
        if not worker_done:
            try:
                os.kill(worker, 9)
                os.waitpid(worker, 0)
            except ProcessLookupError:
                pass


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

def test_atomic_route_migration_rotation_revocation_and_default_model_change(location):
    from haos.provider_routes import ProviderRoutes
    from haos.provider_registry import default_mode
    import json
    tmp_path = location
    def route(provider):
        return {**policy(provider), "api_mode": default_mode(provider)}
    from haos.provider_setup import publish, add_route, route_settings
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    publish(route("openrouter"), first, config=tmp_path)
    original = json.loads((tmp_path / "provider-token").read_text())["token"]
    add_route(route("anthropic"), second, config=tmp_path)
    configuration = ProviderRoutes(json.loads((tmp_path / "provider.json").read_text()))
    envelope = json.loads((tmp_path / "provider-credentials").read_text())
    assert configuration.default == "anthropic" and set(configuration.routes) == {"anthropic", "openrouter"}
    assert envelope == {"routes": {"openrouter": {"api_key": first}, "anthropic": {"api_key": second}}}
    assert json.loads((tmp_path / "provider-token").read_text())["token"] != original
    assert first not in (tmp_path / "provider-client.json").read_text() and second not in (tmp_path / "provider.json").read_text()
    route_settings("openrouter", make_default=True, config=tmp_path)
    route_settings("anthropic", remove=True, config=tmp_path)
    assert second not in (tmp_path / "provider-credentials").read_text()
    assert (tmp_path / "provider-credentials").stat().st_mode & 0o777 == 0o600


def test_account_logout_withdraws_routes_keys_fallbacks_and_dependent_moa_before_remote_logout(location):
    from haos.provider_setup import publish, add_route, configure_ensemble, revoke_account_routes
    from haos.provider_registry import default_mode
    from haos.provider_routes import ProviderRoutes
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    publish({**policy("openrouter"), "api_mode": default_mode("openrouter")}, first, config=location)
    add_route({**policy("anthropic"), "api_mode": default_mode("anthropic")}, second, config=location)
    configure_ensemble("owner", [{"route": "openrouter", "model": "fixture-model"}],
                       {"route": "anthropic", "model": "fixture-model"}, config=location)
    result = revoke_account_routes("anthropic", config=location)
    current = ProviderRoutes(json.loads((location / "provider.json").read_text()))
    assert result["withdrawn_routes"] == 1 and set(current.routes) == {"openrouter"}
    assert not current.ensembles and current.default_ensemble is None
    assert second not in (location / "provider-credentials").read_text()
    assert revoke_account_routes("openrouter", config=location)["withdrawn_routes"] == 1
    assert not (location / "provider.json").exists()
    assert first not in (location / "provider-credentials").read_text()
