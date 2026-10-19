#!/usr/bin/env python3
"""Actual Anthropic SDK -> broker -> native subscription HTTP/SSE fixture."""
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from agent.anthropic_adapter import build_anthropic_kwargs, build_anthropic_client
    from agent.transports import get_transport
    from haos.provider_profiles import register_profiles
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    received, failures = [], []
    state = {}
    release = threading.Event()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.path == "/v1/messages"
                assert body == state["expected"]
                if state["oauth"]:
                    assert self.headers["Authorization"] == "Bearer " + state["key"]
                    assert "oauth-2025-04-20" in self.headers["anthropic-beta"]
                    assert self.headers["user-agent"].startswith("claude-code/")
                    assert self.headers["x-app"] == "cli"
                else:
                    assert self.headers["x-api-key"] == state["key"]
                    assert not self.headers.get("Authorization")
                if state["fast"]:
                    assert "fast-mode-2026-02-01" in self.headers["anthropic-beta"] and body["speed"] == "fast"
                received.append(body)
                name = body["tools"][0]["name"]
                usage = {"input_tokens": 8, "output_tokens": 5}
                message = {"id": "msg_fixture", "type": "message", "role": "assistant", "model": body["model"],
                    "content": [{"type": "text", "text": "fixture " + state["key"]},
                                {"type": "tool_use", "id": "tool_fixture", "name": name, "input": {"x": 1}}],
                    "stop_reason": "tool_use", "stop_sequence": None, "usage": usage}
                if not body.get("stream"):
                    data = json.dumps(message).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                def event(value):
                    # Native SDK parsing must tolerate multiline JSON SSE data,
                    # with secrets divided across arbitrary TCP writes.
                    lines = json.dumps(value, indent=2).splitlines()
                    data = ("event: " + value["type"] + "\n" + "\n".join("data: " + line for line in lines) + "\n\n").encode()
                    for start in range(0, len(data), 7):
                        self.wfile.write(data[start:start + 7])
                    self.wfile.flush()
                event({"type": "message_start", "message": {**message, "content": [], "stop_reason": None,
                    "usage": {"input_tokens": 8, "output_tokens": 0}}})
                event({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "early fixture " + state["key"]}})
                assert release.wait(5), "SDK did not expose a delta before upstream completion"
                event({"type": "content_block_stop", "index": 0})
                event({"type": "content_block_start", "index": 1,
                    "content_block": {"type": "tool_use", "id": "tool_fixture", "name": name, "input": {}}})
                event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"x":1}'}})
                event({"type": "content_block_stop", "index": 1})
                event({"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 5}})
                event({"type": "message_stop"})
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    original_https = http.client.HTTPSConnection
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream_port:
        def fixture_https(host, port=443, **kwargs):
            assert host == "api.anthropic.com" and port == 443
            return http.client.HTTPConnection("127.0.0.1", upstream_port, timeout=kwargs.get("timeout", 5))
        http.client.HTTPSConnection = fixture_https
        try:
            for oauth in (False, True):
                for streaming, fast in ((False, False), (True, False), (True, True)):
                    model = "claude-opus-4-8" if fast else "claude-opus-4-6"
                    key = ("sk-ant-oat01-" if oauth else "sk-ant-api03-") + secrets.token_urlsafe(40)
                    policy = ProviderPolicy({"version": 1, "provider": "anthropic", "endpoint": "https://api.anthropic.com",
                        "models": [model], "default_model": model, "api_mode": "anthropic_messages",
                        "requests_per_day": 200, "requests_per_minute": 30})
                    register_profiles(policy.data)
                    messages = [{"role": "system", "content": "Hermes Agent by Nous Research: session_search"},
                        {"role": "user", "content": "fixture"}, {"role": "assistant", "content": "previous fixture",
                        "reasoning_details": [{"type": "thinking", "thinking": "fixture thought", "signature": "fixture-signature"}]}]
                    # Alias collision and MCP prefix handling use the exact
                    # native helper; the broker restores this request's names.
                    tools = [{"type": "function", "function": {"name": name, "description": "session_search in Hermes Agent",
                        "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}}
                        for name in ("memory", "context_notes", "session_search", "mcp_linear_lookup")]
                    options = {"max_tokens": 2048, "reasoning_config": None, "tool_choice": "memory", "fast_mode": fast}
                    body = get_transport("anthropic_messages").build_kwargs(model, messages, tools,
                        base_url=policy.client_config()["model"]["base_url"], **options)
                    expected = build_anthropic_kwargs(model, messages, tools,
                        base_url=policy.endpoint, is_oauth=oauth, **options)
                    expected.pop("extra_headers", None)
                    expected.update(expected.pop("extra_body", {}))
                    if streaming:
                        expected["stream"] = True
                    state.update(expected=expected, key=key, oauth=oauth, fast=fast)
                    release.clear()
                    with tempfile.TemporaryDirectory() as temp:
                        ledger = UsageLedger(Path(temp) / "usage.db")
                        capability = secrets.token_urlsafe(48)
                        credentials = Credentials(policy, {"api_key": key})
                        with serving(Broker(("127.0.0.1", 0), policy, capability, credentials, ledger)) as port:
                            with build_anthropic_client(capability, f"http://127.0.0.1:{port}/v1", timeout=10) as client:
                                if streaming:
                                    with client.messages.stream(**body) as stream:
                                        first = next(iter(stream.text_stream))
                                        assert first.startswith("early fixture ") and key not in first
                                        release.set()
                                        result = stream.get_final_message()
                                else:
                                    result = client.messages.create(**body)
                                assert key not in result.model_dump_json() and capability not in result.model_dump_json()
                                assert result.content[1].name == "memory" and result.content[1].input == {"x": 1}
                                normalized = get_transport("anthropic_messages").normalize_response(result)
                                assert normalized.tool_calls[0].name == "memory" and normalized.finish_reason == "tool_calls"
                        assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [(200, 8, 5)]
                        ledger.close()
        finally:
            http.client.HTTPSConnection = original_https
            release.set()
    assert len(received) == 6 and not failures
    receipt = {"actual_anthropic_sdk_api_key_and_subscription_json_sse": True,
        "actual_pinned_subscription_body_and_header_contract": True, "signed_thinking_replay_preserved": True,
        "forced_tool_alias_collision_mcp_names_restored": True, "multiline_sse_and_early_delta_before_terminal": True,
        "native_fast_mode_body_beta_preserved": True,
        "reflected_private_tokens_redacted": True, "actual_loopback_http_cases": len(received),
        "live_provider_tested": False, "python": sys.version.split()[0],
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
            (Path(__file__), root / "haos/provider_profiles.py", root / "haos/provider_messages.py",
             root / "haos/provider_sse.py", root / "haos/provider_proxy.py")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
