import os

import pytest

from haos import launch
from haos.sandbox import command


def test_credential_value_never_enters_the_launcher_arguments(monkeypatch):
    # Credential unit cases isolate the preceding kernel guard; its actual
    # abstract/named socket behavior is verified in the disposable Fedora VM.
    monkeypatch.setattr("haos.ipc_scope.restrict_abstract_sockets", lambda: 6)
    token = "fixture-" + "x" * 56
    monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "before")
    monkeypatch.setattr("haos.launch.Path.read_text", lambda self: token)
    calls = []
    monkeypatch.setattr("haos.launch.os.execv", lambda executable, args: calls.append((executable, args)))
    launch.main()
    assert os.environ["HERMES_DASHBOARD_SESSION_TOKEN"] == token
    assert calls and token not in " ".join(calls[0][1])
    assert token not in " ".join(command([], 3, certificates=[]))


@pytest.mark.parametrize("value", ["", " ", "short", "x" * 43 + "\nsecret", "x" * 129])
def test_invalid_credentials_cannot_launch_a_backend(monkeypatch, value):
    monkeypatch.setattr("haos.ipc_scope.restrict_abstract_sockets", lambda: 6)
    monkeypatch.setattr("haos.launch.Path.read_text", lambda self: value)
    monkeypatch.setattr("haos.launch.os.execv", lambda *args: pytest.fail("invalid credential launched backend"))
    with pytest.raises(ValueError, match="credential"):
        launch.main()


def test_runtime_model_config_seals_current_and_exact_legacy_without_mutation():
    import copy
    import fcntl
    import json
    import os
    import pytest
    from haos.provider_routes import ProviderRoutes
    from haos.sandbox import runtime_provider_config
    policy = ProviderRoutes({'version': 1, 'provider': 'local', 'endpoint': 'http://127.0.0.1:11434/v1',
        'models': ['fixture-model'], 'default_model': 'fixture-model', 'api_mode': 'chat_completions',
        'requests_per_day': 200, 'requests_per_minute': 120})
    expected = policy.client_config()
    assert expected['agent'] == {'api_max_retries': 1, 'auto_recovery_cycles': 0}
    for client in (expected, {key: value for key, value in expected.items() if key != 'agent'}):
        before = copy.deepcopy(client)
        descriptor = runtime_provider_config(policy, client)
        try:
            assert json.loads(os.read(descriptor, 65536)) == expected
            assert os.get_inheritable(descriptor)
            for mutation in (lambda: os.write(descriptor, b'x'), lambda: os.ftruncate(descriptor, 0), lambda: os.ftruncate(descriptor, 65536)):
                with pytest.raises(OSError): mutation()
            assert fcntl.fcntl(descriptor, getattr(fcntl, "F_GET_SEALS", 1034)) & getattr(fcntl, "F_SEAL_WRITE", 8)
        finally: os.close(descriptor)
        assert client == before
    for changes in ({'agent': {'api_max_retries': 3, 'auto_recovery_cycles': 0}},
            {'agent': {}}, {'model': {**expected['model'], 'base_url': 'https://unapproved.invalid'}}, {'unknown': True}):
        with pytest.raises(PermissionError): runtime_provider_config(policy, {**expected, **changes})


def test_sandbox_uses_a_separate_read_only_model_config_descriptor():
    import pytest
    args = command([], 7, certificates=[], provider_fd=8, provider_config_fd=9, ui_fd=10)
    assert '/etc/haos/provider-client.json' not in args
    target = args.index('/home/agent/.hermes/config.yaml')
    assert args[target - 4:target] == ['--perms', '0400', '--ro-bind-data', '9']
    for bad in (True, -1, 2, 7, 8, 10):
        with pytest.raises(ValueError): command([], 7, certificates=[], provider_fd=8, provider_config_fd=bad, ui_fd=10)
    with pytest.raises(ValueError): command([], 7, certificates=[], provider_config_fd=9)
