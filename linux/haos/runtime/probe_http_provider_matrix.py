#!/usr/bin/env python3
"""Real pinned builders/SDKs and broker HTTP; explicit fixtures, never inference."""
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
from urllib.parse import urlsplit


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


def fixture_response(mode, model, name, text):
    """Native fixture messages shared by HTTP and actual cloud-SDK probes."""
    if mode == "anthropic_messages":
        result = {"id": "msg_fixture", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": text},
                {"type": "tool_use", "id": "call_fixture", "name": name, "input": {"x": 1}}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 8, "output_tokens": 5}}
        early = [{"type": "message_start", "message": {**result, "content": [], "stop_reason": None,
            "usage": {"input_tokens": 8, "output_tokens": 0}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}]
        terminal = [{"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1,
                "content_block": {"type": "tool_use", "id": "call_fixture", "name": name, "input": {}}},
            {"type": "content_block_delta", "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"x":1}'}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 5}}, {"type": "message_stop"}]
    elif mode == "codex_responses":
        message = {"type": "message", "id": "msg_fixture", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}]}
        tool = {"type": "function_call", "id": "fc_fixture", "call_id": "call_fixture",
            "name": name, "arguments": '{"x":1}', "status": "completed"}
        result = {"id": "resp_fixture", "object": "response", "created_at": 1, "model": model,
            "status": "completed", "error": None, "incomplete_details": None,
            "output": [message, tool],
            "usage": {"input_tokens": 8, "output_tokens": 5, "total_tokens": 13}}
        early = [{"type": "response.created", "response": {**result, "status": "in_progress", "output": [], "usage": None}},
            {"type": "response.output_item.added", "output_index": 0, "item": {**message, "status": "in_progress", "content": []}},
            {"type": "response.content_part.added", "item_id": "msg_fixture", "output_index": 0, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []}},
            {"type": "response.output_text.delta", "item_id": "msg_fixture", "output_index": 0,
                "content_index": 0, "delta": text, "logprobs": []}]
        terminal = [{"type": "response.output_text.done", "item_id": "msg_fixture", "output_index": 0, "content_index": 0,
                "text": text, "logprobs": []},
            {"type": "response.content_part.done", "item_id": "msg_fixture", "output_index": 0, "content_index": 0, "part": message["content"][0]},
            {"type": "response.output_item.done", "output_index": 0, "item": message},
            {"type": "response.output_item.added", "output_index": 1, "item": {**tool, "arguments": "", "status": "in_progress"}},
            {"type": "response.function_call_arguments.delta", "item_id": "fc_fixture", "output_index": 1, "delta": '{"x":1}'},
            {"type": "response.function_call_arguments.done", "item_id": "fc_fixture", "output_index": 1, "arguments": '{"x":1}', "name": name},
            {"type": "response.output_item.done", "output_index": 1, "item": tool},
            {"type": "response.completed", "response": result}]
        for sequence, value in enumerate([*early, *terminal]):
            value["sequence_number"] = sequence
    else:
        result = {"id": "chat_fixture", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant",
                "content": text, "tool_calls": [{"id": "call_fixture", "type": "function",
                    "function": {"name": name, "arguments": '{"x":1}'}}]}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13}}
        early = [{"id": "chat_fixture", "object": "chat.completion.chunk", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": None, "delta": {"role": "assistant", "content": text}}]}]
        terminal = [{**early[0], "choices": [{"index": 0, "finish_reason": "tool_calls",
            "delta": {"tool_calls": [{"index": 0, **result["choices"][0]["message"]["tool_calls"][0]}]}}],
            "usage": result["usage"]}, "[DONE]"]
    return result, early, terminal


@contextmanager
def sdk_stream(client, mode, call, body, *, accumulate=False):
    manager = (client.responses.stream(**body) if accumulate and mode == "codex_responses" else
        client.messages.stream(**body) if accumulate and mode == "anthropic_messages" else call(**body, stream=True))
    with manager as stream:
        yield stream


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import anthropic
    import httpx
    import openai
    from agent.transports import get_transport
    from haos.provider_policy import ProviderPolicy
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_registry import http_providers, descriptor, default_mode, default_endpoint

    state, received, failures, checks = {}, [], [], []
    release = threading.Event()
    finished = threading.Event()

    class FixtureLedger(UsageLedger):
        def finish(self, *args, **kwargs):
            super().finish(*args, **kwargs)
            finished.set()

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                mode, case = state["mode"], state["case"]
                assert self.path == state["path"]
                assert body["model"] == state["wire_model"]
                assert body.get("stream", False) == (case in {"stream", "abort", "stream-framing", "chunked-stream", "chunked-framing", "chunked-trailer"})
                assert len(body["tools"]) == 1
                tool = body["tools"][0]
                name = tool.get("name") or tool["function"]["name"]
                assert name == "fixture"
                if state["key"]:
                    assert state["key"] in " ".join(self.headers.values())
                else:
                    assert not self.headers.get("Authorization") and not self.headers.get("x-api-key")
                assert state["capability"] not in " ".join(self.headers.values())
                assert not self.headers.get("Cookie")
                received.append((state["provider"], case))
                if case in {"401", "429"}:
                    data = json.dumps({"error": {"message": state["key"] or "local-fixture-error", "type": "fixture_error"}}).encode()
                    self.send_response(int(case))
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                text = "early fixture " + (state["key"] or "no-local-credential")
                result, early, terminal = fixture_response(mode, body["model"], name, text)
                if case in {"json", "json-framing"}:
                    data = json.dumps(result).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data) + (16 if case == "json-framing" else 0)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                    self.close_connection = True
                    return
                def frame(value):
                    # Anthropic dispatches on the named SSE event, not just the
                    # JSON type. Emit a complete valid native event sequence.
                    prefix = "event: " + value["type"] + "\n" if mode == "anthropic_messages" else ""
                    data = value if isinstance(value, str) else json.dumps(value)
                    return (prefix + "data: " + data + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                if case == "stream-framing":
                    self.send_header("Content-Length", str(sum(len(frame(value)) for value in [*early, *terminal]) + 16))
                if case in {"chunked-stream", "chunked-framing", "chunked-trailer"}:
                    self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def event(value):
                    data = frame(value)
                    if case in {"chunked-stream", "chunked-framing", "chunked-trailer"}:
                        data = f"{len(data):x}\r\n".encode() + data + b"\r\n"
                    self.wfile.write(data)
                    self.wfile.flush()

                for value in early:
                    event(value)
                assert release.wait(5), "SDK buffered the first delta until terminal"
                if case != "abort":
                    for value in terminal:
                        event(value)
                if case == "chunked-stream":
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                elif case == "chunked-trailer":
                    self.wfile.write(b"0\r\n")
                    self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append((state["provider"], state["case"], type(error).__name__))
                raise

    original_https = http.client.HTTPSConnection
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream_port:
        def fixture_https(host, port=443, **kwargs):
            assert host == urlsplit(state["endpoint"]).hostname and port == 443
            return http.client.HTTPConnection("127.0.0.1", upstream_port, timeout=kwargs.get("timeout", 5))
        http.client.HTTPSConnection = fixture_https
        try:
            providers = sorted(http_providers()) + ["lmstudio", "local"]
            assert len(http_providers()) == 39 and len(providers) == 41
            for provider in providers:
                row = descriptor(provider)
                model = next(iter(row["fallback_models"]), "fixture-model") if row else "fixture-model"
                mode, endpoint = default_mode(provider, model), default_endpoint(provider)
                if provider in {"lmstudio", "local"}:
                    endpoint = f"http://127.0.0.1:{upstream_port}/v1"
                policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": endpoint,
                    "models": [model], "default_model": model, "api_mode": mode,
                    "requests_per_day": 200, "requests_per_minute": 120})
                register_profiles(policy.data)
                transport = get_transport(mode)
                body = transport.build_kwargs(model, [{"role": "user", "content": "fixture-only prompt"}],
                    [{"type": "function", "function": {"name": "fixture", "description": "local fixture",
                        "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}}],
                    base_url=policy.client_config()["model"]["base_url"], max_tokens=1024, reasoning_config=None)
                wire_model = body["model"]
                path = urlsplit(endpoint).path.rstrip("/")
                if mode == "anthropic_messages" and not path.endswith("/v1"):
                    path += "/v1"
                path += {"anthropic_messages": "/messages", "codex_responses": "/responses",
                    "chat_completions": "/chat/completions"}[mode]
                for case in ("json", "stream", "abort", "401", "429", "json-framing", "stream-framing", "chunked-stream", "chunked-framing", "chunked-trailer"):
                    print(provider + ":" + case, flush=True)
                    release.clear()
                    finished.clear()
                    key, capability = (None if provider in {"local", "lmstudio"} else secrets.token_urlsafe(40)), secrets.token_urlsafe(48)
                    state.update(provider=provider, case=case, mode=mode, endpoint=endpoint,
                        path=path, wire_model=wire_model, key=key, capability=capability)
                    with tempfile.TemporaryDirectory() as temp:
                        ledger = FixtureLedger(Path(temp) / "usage.db")
                        with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": key}), ledger)) as port:
                            cls = anthropic.Anthropic if mode == "anthropic_messages" else openai.OpenAI
                            base = f"http://127.0.0.1:{port}" + ("" if mode == "anthropic_messages" else "/v1")
                            with cls(api_key=capability, base_url=base, timeout=10,
                                    max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                                call = (client.messages.create if mode == "anthropic_messages" else
                                    client.responses.create if mode == "codex_responses" else client.chat.completions.create)
                                if case in {"401", "429", "json-framing"}:
                                    try:
                                        call(**body)
                                    except (anthropic.APIStatusError, openai.APIStatusError) as error:
                                        assert error.status_code == (502 if case == "json-framing" else int(case))
                                        assert (not key or key not in str(error)) and capability not in str(error)
                                    else:
                                        raise AssertionError("SDK accepted rejected request")
                                elif case == "json":
                                    result = call(**body)
                                    normalized = transport.normalize_response(result)
                                    assert normalized.tool_calls[0].name == "fixture"
                                    assert json.loads(normalized.tool_calls[0].arguments) == {"x": 1}
                                    assert (not key or key not in result.model_dump_json()) and capability not in result.model_dump_json()
                                else:
                                    first = False
                                    values = []
                                    interrupted = False
                                    try:
                                        with sdk_stream(client, mode, call, body, accumulate=case in {"stream", "chunked-stream"}) as stream:
                                            for value in stream:
                                                values.append(value)
                                                encoded = value.model_dump_json()
                                                assert (not key or key not in encoded) and capability not in encoded
                                                if not first and "early fixture " in encoded:
                                                    assert not release.is_set()
                                                    first = True
                                                    release.set()
                                            if case in {"stream", "chunked-stream"} and mode in {"codex_responses", "anthropic_messages"}:
                                                result = stream.get_final_response() if mode == "codex_responses" else stream.get_final_message()
                                                normalized = transport.normalize_response(result)
                                                assert normalized.tool_calls[0].name == "fixture"
                                                assert json.loads(normalized.tool_calls[0].arguments) == {"x": 1}
                                                assert normalized.content.startswith("early fixture ") and (not key or key not in normalized.content)
                                    except httpx.RemoteProtocolError:
                                        interrupted = True
                                    assert first, "SDK lost early text delta"
                                    assert interrupted == (case in {"abort", "stream-framing", "chunked-framing", "chunked-trailer"}), "incomplete stream certified successful"
                                    if case in {"stream-framing", "chunked-framing", "chunked-trailer"}:
                                        assert not any(getattr(value, "type", None) in {"message_stop", "response.completed"}
                                            or any(choice.finish_reason is not None for choice in getattr(value, "choices", []))
                                            for value in values), "unverified terminal was forwarded"
                                    if case in {"stream", "chunked-stream"}:
                                        assert any("call_fixture" in value.model_dump_json() for value in values)
                        expected = (502, None, None) if case in {"abort", "json-framing", "stream-framing", "chunked-framing", "chunked-trailer"} else (
                            (int(case), None, None) if case in {"401", "429"} else (200, 8, 5))
                        assert finished.wait(5), "broker did not durably finalize admission"
                        assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [expected]
                        ledger.close()
                    checks.append(provider + ":" + case)
        finally:
            release.set()
            http.client.HTTPSConnection = original_https
    assert not failures, failures
    assert len(received) == len(checks) == 410 and len(set(received)) == 410
    receipt = {"actual_pinned_builder_sdk_http_cases": checks, "http_profile_count": len(http_providers()), "local_service_profiles": ["lmstudio", "local"],
        "case_count": len(checks), "early_stream_before_withheld_terminal": True,
        "truncated_streams_rejected_without_retry": True, "native_tool_json_preserved": True,
        "incomplete_http_framing_cannot_certify_json_or_terminal_sse": True,
        "private_credential_reflection_redacted": True, "live_provider_tested": False,
        "python": sys.version.split()[0], "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), root / "haos/provider_messages.py", root / "haos/provider_proxy.py", root / "haos/provider_sse.py",
                root / "haos/provider_profiles.py", root / "haos/hermes_registry.json")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(checks), "live_provider_tested": False}))


if __name__ == "__main__":
    main()
