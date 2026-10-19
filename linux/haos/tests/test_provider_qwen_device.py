"""Admission checks do not require Hermes or a live provider account."""
import pytest

from haos.provider_qwen import _authorization, device_login, QwenLoginError


def authorization(**changes):
    return {"user_code": "ABCD-EFGH", "device_code": "private-device-fixture-00000000",
        "verification_uri_complete": "https://chat.qwen.ai/authorize?user_code=ABCD-EFGH",
        "expires_in": 600, **changes}


def test_device_user_authorization_is_fixed_to_qwen_and_bounded():
    device, uri, code, expiry, interval = _authorization(authorization())
    assert device == "private-device-fixture-00000000" and code == "ABCD-EFGH"
    assert uri == "https://chat.qwen.ai/authorize?user_code=ABCD-EFGH" and expiry == 600 and interval == 2


@pytest.mark.parametrize("change", [
    {"verification_uri_complete": "https://attacker.invalid/authorize?user_code=ABCD-EFGH"},
    {"verification_uri_complete": "http://chat.qwen.ai/authorize?user_code=ABCD-EFGH"},
    {"verification_uri_complete": "https://chat.qwen.ai:443/authorize?user_code=ABCD-EFGH"},
    {"verification_uri_complete": "https://chat.qwen.ai@attacker.invalid/authorize?user_code=ABCD-EFGH"},
    {"verification_uri_complete": "https://chat.qwen.ai/authorize?user_code=OTHER"},
    {"verification_uri_complete": "https://chat.qwen.ai/authorize?user_code=ABCD-EFGH&user_code=OTHER"},
    {"verification_uri_complete": "https://chat.qwen.ai/authorize?user_code=ABCD-EFGH#secret"},
    {"verification_uri_complete": "https://chat.qwen.ai/authorize?device_code=secret"},
    {"user_code": "ABCD\nINJECTED"}, {"device_code": "short"}, {"device_code": "x" * 4097},
    {"expires_in": True}, {"expires_in": 0}, {"expires_in": 3601},
    {"interval": 0}, {"interval": 31}, {"interval": 0.1},
])
def test_device_grant_cannot_redirect_render_private_codes_or_remove_timing_limits(change):
    with pytest.raises((QwenLoginError, ValueError)):
        _authorization(authorization(**change))


@pytest.mark.parametrize("timeout", [True, 0, 601, "600"])
def test_invalid_local_timeouts_fail_before_optional_runtime_import(timeout):
    with pytest.raises(ValueError):
        device_login(timeout=timeout)


def test_graphical_account_status_uses_private_helper_without_stopping_execution(monkeypatch):
    from haos import initial_setup, initial_setup_gui, provider_setup
    calls = []
    monkeypatch.setattr(initial_setup, "require_root", lambda: None)
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: True)
    monkeypatch.setattr(initial_setup, "quiesce_for_setup", lambda: pytest.fail("status must not stop execution"))
    monkeypatch.setattr(provider_setup, "auth_helper", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert initial_setup.provider_account("qwen-oauth", "status") == {
        "credential_action_completed": True, "model_turn_tested": False}
    assert calls == [(("status", "qwen-oauth"), {"graphical_status": True})]
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: False)
    with pytest.raises(PermissionError):
        initial_setup.provider_account("qwen-oauth", "status")
    assert len(calls) == 1
