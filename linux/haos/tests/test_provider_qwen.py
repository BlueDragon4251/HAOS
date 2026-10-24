import json
import pytest
from haos.provider_auth import qwen_import


def value():
    return {"access_token": "fixture-access-token-000000000", "refresh_token": "fixture-refresh-token-000000000",
            "expiry_date": 1234567890000, "token_type": "Bearer", "resource_url": "portal.qwen.ai"}


def test_qwen_cli_import_keeps_the_upstream_token_shape_and_fixed_service():
    assert qwen_import(json.dumps(value())) == value()


@pytest.mark.parametrize("change", [{"resource_url": "https://attacker.invalid"}, {"expiry_date": True},
                                  {"access_token": "injected\nheader"}, {"token_uri": "https://attacker.invalid/token"}])
def test_qwen_import_cannot_redirect_credentials_or_inject_headers(change):
    with pytest.raises((ValueError, PermissionError)):
        qwen_import(json.dumps({**value(), **change}))
