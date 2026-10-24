import json
import pytest

from haos.provider_cloud import credential_data, mantle_endpoint
from haos.provider_policy import ProviderPolicy
from haos.provider_registry import default_mode
from haos.provider_bedrock_replay import carrier, restore, TYPE

ENDPOINT = "https://bedrock-runtime.eu-central-1.amazonaws.com"


@pytest.mark.parametrize("model,mode", [
    ("openai.gpt-5.5", "codex_responses"), ("openai.gpt-5.6-sol", "codex_responses"),
    ("openai.gpt-oss-120b-1:0", "chat_completions"),
    ("anthropic.claude-opus-4-6-v1", "anthropic_messages"),
    ("global.anthropic.claude-opus-4-6-v1", "anthropic_messages"),
    ("eu.anthropic.claude-sonnet-4-5-20250929-v1:0", "anthropic_messages"),
    ("amazon.nova-pro-v1:0", "chat_completions"),
])
def test_native_bedrock_model_rules_keep_gpt_oss_on_converse(model, mode):
    assert default_mode("bedrock", model) == mode
    data = {"version": 1, "provider": "bedrock", "endpoint": ENDPOINT, "models": [model],
        "default_model": model, "api_mode": mode, "requests_per_day": 200, "requests_per_minute": 30}
    assert ProviderPolicy(data).api_mode == mode
    for other in {"codex_responses", "anthropic_messages", "chat_completions"} - {mode}:
        if other == "chat_completions" and mode == "anthropic_messages":
            continue  # Existing explicit Claude Converse policies stay usable.
        with pytest.raises(ValueError):
            ProviderPolicy({**data, "api_mode": other})


@pytest.mark.parametrize("data", [
    {"bearer_token": "fixture", "profile": "other"},
    {"bearer_token": "fixture\ninjected: header"}, {"bearer_token": {"bad": "value"}},
    {"bearer_token": ""}, {"bearer_token": "with space"},
])
def test_bearer_cannot_mix_auth_or_inject_headers(data):
    with pytest.raises(ValueError):
        credential_data("bedrock", json.dumps(data))


def test_mantle_endpoint_has_only_the_owner_approved_region():
    assert mantle_endpoint(ENDPOINT) == "https://bedrock-mantle.eu-central-1.api.aws/openai/v1"
    for value in (ENDPOINT + "/admin", ENDPOINT + "?key=fixture", "https://attacker.invalid"):
        with pytest.raises(PermissionError):
            mantle_endpoint(value)


def test_replay_is_bound_to_model_endpoint_and_preserves_original_history():
    blocks = [{"reasoningContent": {"text": "fixture thought", "signature": "fixture signature"}},
              {"toolUse": {"toolUseId": "fixture", "name": "fixture", "input": {}}}]
    detail = carrier(blocks, "fixture-model", ENDPOINT)
    history = [{"role": "assistant", "content": "fixture", "reasoning_details": [detail]}]
    assert restore(history, "fixture-model", ENDPOINT)[0]["bedrock_content_blocks"] == blocks
    for model, endpoint in (("other-model", ENDPOINT), ("fixture-model", ENDPOINT.replace("eu-central-1", "us-east-1"))):
        result = restore(history, model, endpoint)[0]
        assert "bedrock_content_blocks" not in result and result["reasoning_details"] == []
    assert history[0]["reasoning_details"][0]["type"] == TYPE and "bedrock_content_blocks" not in history[0]
