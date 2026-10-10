import os

import pytest

from haos import launch
from haos.sandbox import command


def test_credential_value_never_enters_the_launcher_arguments(monkeypatch):
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
    monkeypatch.setattr("haos.launch.Path.read_text", lambda self: value)
    monkeypatch.setattr("haos.launch.os.execv", lambda *args: pytest.fail("invalid credential launched backend"))
    with pytest.raises(ValueError, match="credential"):
        launch.main()
