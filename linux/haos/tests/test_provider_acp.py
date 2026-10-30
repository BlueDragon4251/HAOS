import io
import json
import socket
import struct
import pytest
from haos.provider_acp import TextFilter, frame, require_peer, ARGS
from haos.provider_acp_network import acp_rules
from haos.provider_policy import ProviderPolicy
from haos.provider_proxy import Credentials
from haos.provider_setup import validate_credential
from haos.redaction import Redactor


def policy(**changes):
    return ProviderPolicy({"version": 1, "provider": "copilot-acp", "endpoint": "acp://copilot",
        "models": ["fixture"], "default_model": "fixture", "api_mode": "chat_completions",
        "requests_per_day": 200, "requests_per_minute": 30, **changes})


def test_acp_route_accepts_no_arbitrary_process_endpoint_or_broker_key():
    p = policy()
    assert Credentials(p, {"api_key": None}).headers()[0] == {}
    validate_credential(p, None)
    for endpoint in ("acp://attacker", "file:///bin/sh", "https://api.githubcopilot.com", "acp://copilot?args=--allow-all"):
        with pytest.raises(PermissionError):
            policy(endpoint=endpoint)
    with pytest.raises(PermissionError):
        validate_credential(p, "fixture-private-key-00000000000000")
    with pytest.raises(ValueError):
        policy(api_mode="codex_responses")
    assert "--available-tools=" in ARGS and "--disable-builtin-mcps" in ARGS


def test_native_acp_tool_markup_and_credentials_are_hidden_across_every_chunk_boundary():
    secret = "fixture-long-private-token-0123456789"
    data = "Live text " + secret + ' <tool_call>{"function":{"name":"terminal","arguments":"{}"}}</tool_call> after'
    for width in range(1, len(secret) + 3):
        out = []
        filtered = TextFilter(Redactor([secret]), out.append)
        for start in range(0, len(data), width):
            filtered.feed(data[start:start + width])
        filtered.feed("", final=True)
        assert "".join(out) == "Live text [REDACTED]  after"


def test_acp_truncated_tool_output_and_invalid_frames_fail_closed():
    filtered = TextFilter(Redactor(), lambda _: None)
    filtered.feed("Text <tool_call>{")
    with pytest.raises(ValueError):
        filtered.feed("", final=True)
    for data in (b'{"ok":true}', b'[]\n', b'{"ok":true}\n' * 10):
        with pytest.raises(ValueError):
            frame(io.BytesIO(data), 8)


def test_acp_peer_requires_exact_nonroot_kernel_identity():
    class Peer:
        def getsockopt(self, *args):
            assert args == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", 1234, 5678, 5678)
    require_peer(Peer(), 5678)
    for uid in (0, True, 5679):
        with pytest.raises(PermissionError):
            require_peer(Peer(), uid)


def test_external_cli_cannot_connect_to_controller_provider_or_private_networks():
    script = acp_rules(6789, ["10.0.0.1"])
    assert "haos_provider_acp" in script and "meta skuid 6789" in script
    assert "dport 9119" not in script and "dport 9120" not in script
    assert "ip daddr 10.0.0.1 udp dport 53 counter accept" in script
    assert "fib daddr type local counter reject" in script
    assert "169.254.0.0/16" in script and "fc00::/7" in script
