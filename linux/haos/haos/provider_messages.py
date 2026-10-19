"""Native subscription wire transforms, confined to the private broker."""
from copy import deepcopy


def feature_headers(payload, headers, endpoint):
    if payload.get("speed") != "fast":
        return headers
    from agent.anthropic_adapter import _supports_fast_mode, _FAST_MODE_BETA
    from agent.anthropic_endpoints import _is_third_party_anthropic_endpoint
    if not _is_third_party_anthropic_endpoint(endpoint) and _supports_fast_mode(payload.get("model", "")):
        headers = dict(headers)
        key = next((key for key in headers if key.lower() == "anthropic-beta"), "anthropic-beta")
        betas = headers.get(key, "").split(",")
        headers[key] = ",".join(dict.fromkeys([*(beta for beta in betas if beta), _FAST_MODE_BETA]))
    return headers


def prepare(payload, *, oauth=False):
    if not oauth:
        return payload, {}
    from agent.anthropic_adapter import _oauth_wire_namer, _apply_claude_code_identity
    body = deepcopy(payload)
    tools = body.get("tools", [])
    to_wire = _oauth_wire_namer(tools)
    reverse = {to_wire(tool["name"]): tool["name"] for tool in tools}
    if len(reverse) != len(tools):
        raise ValueError("subscription tool wire names collide")
    body["system"] = _apply_claude_code_identity(body.get("system"), tools, body.get("messages", []), to_wire)
    choice = body.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") == "tool" and isinstance(choice.get("name"), str):
        choice["name"] = to_wire(choice["name"])
    return body, reverse


def restore(value, names):
    """Restore only exact request-owned names in native tool-use blocks."""
    if isinstance(value, list):
        return [restore(item, names) for item in value]
    if isinstance(value, dict):
        return {key: names.get(item, item) if key == "name" and value.get("type") == "tool_use" and isinstance(item, str)
                else restore(item, names) for key, item in value.items()}
    return value
