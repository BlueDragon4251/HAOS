"""Policy and real local HTTP transport checks, not external model acceptance."""

from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time

import pytest

from haos.provider_policy import ENDPOINTS, ProviderPolicy
from haos.provider_proxy import Broker, Credentials, UsageLedger


def policy(provider="openai-codex", **changes):
    return {"version": 1, "provider": provider, "endpoint": ENDPOINTS.get(provider, "http://127.0.0.1:11434/v1"),
            "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "codex_responses",
            "requests_per_day": 20, "requests_per_minute": 10, **changes}


@pytest.mark.parametrize("provider,endpoint", [
    ("openai-codex", "http://chatgpt.com/backend-api/codex"),
    ("openai", "https://api.openai.com.evil.invalid/v1"),
    ("openai", "https://api.openai.com/v1?token=x"),
    ("local", "http://localhost:11434/v1"), ("local", "http://127.0.0.1:9119/v1"),
    ("local", "http://user:password@127.0.0.1:11434/v1"), ("local", "http://127.0.0.1:11434/v1#x"),
])
def test_endpoint_cannot_redirect_credentials_or_open_local_administration(provider, endpoint):
    with pytest.raises((PermissionError, ValueError)):
        ProviderPolicy(policy(provider, endpoint=endpoint))


@pytest.mark.parametrize("path,data", [
    ("/v1/responses?url=https://evil.invalid", {"model": "fixture-model"}),
    ("/v1/files", {"model": "fixture-model"}), ("/v1/responses", {"model": "unapproved"}),
    ("/v1/responses", {"model": "fixture-model", "tools": [{"type": "mcp", "server_url": "https://evil.invalid"}]}),
    ("/v1/responses", {"model": "fixture-model", "background": False}),
    ("/v1/responses", {"model": "fixture-model", "previous_response_id": "private"}),
])
def test_caller_cannot_grant_external_tools_or_remote_state(path, data):
    with pytest.raises((PermissionError, ValueError)):
        ProviderPolicy(policy()).request(path, data)


def test_codex_wire_settings_keep_functions_without_persistent_remote_state():
    payload = {"model": "fixture-model", "instructions": "Owner task", "input": [], "stream": True,
               "tools": [{"type": "function", "name": "terminal", "parameters": {"type": "object"}}],
               "store": True, "max_output_tokens": 8192, "temperature": 0.8, "prompt_cache_retention": "24h"}
    result = ProviderPolicy(policy()).request("/v1/responses", payload)
    assert result["tools"] == payload["tools"] and result["store"] is False
    assert not {"max_output_tokens", "temperature", "prompt_cache_retention"} & set(result)
    assert payload["store"] is True


def test_admission_and_limits_survive_restart_and_uncertain_dispatch(tmp_path):
    p = ProviderPolicy(policy(requests_per_minute=1, requests_per_day=2))
    ledger = UsageLedger(tmp_path / "usage.db")
    first = ledger.admit(p, "fixture-model", now=1000)
    ledger.close()  # Admission already durable, no completion receipt supplied.
    ledger = UsageLedger(tmp_path / "usage.db")
    with pytest.raises(PermissionError):
        ledger.admit(p, "fixture-model", now=1001)
    second = ledger.admit(p, "fixture-model", now=1061)
    ledger.finish(second, 200, {"input_tokens": 5, "output_tokens": 7})
    with pytest.raises(PermissionError):
        ledger.admit(p, "fixture-model", now=1122)
    assert ledger.db.execute("SELECT status FROM requests WHERE id=?", (first,)).fetchone() == (None,)
    assert ledger.db.execute("SELECT input_tokens,output_tokens FROM requests WHERE id=?", (second,)).fetchone() == (5, 7)
    assert first != ledger.admit(p, "fixture-model", now=1000 + 86401)
    ledger.close()


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("streaming", [False, True])
def test_actual_local_transport_authenticates_bounds_and_redacts_without_claiming_model_execution(tmp_path, streaming):
    received, key = [], secrets.token_urlsafe(48)

    class LocalFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            # A deliberately hostile local test fixture tries to reflect its
            # bearer key. This is a transport fixture, never model evidence.
            event = {"fixture": True, "content": key, "usage": {"prompt_tokens": 8, "completion_tokens": 3}}
            body = (b"data: " + json.dumps(event).encode() + b"\n\ndata: [DONE]\n\n") if streaming else json.dumps(event).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # Split the credential across multiple TCP writes.
            for byte in body:
                self.wfile.write(bytes([byte]))
            self.wfile.flush()

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), LocalFixture)
    with serving(upstream) as upstream_port:
        p = ProviderPolicy(policy("local", endpoint=f"http://127.0.0.1:{upstream_port}/v1", api_mode="chat_completions"))
        ledger = UsageLedger(tmp_path / "usage.db")
        token = secrets.token_urlsafe(48)
        broker = Broker(("127.0.0.1", 0), p, token, Credentials(p, {"api_key": key}), ledger)
        with serving(broker) as port:
            def request(data, auth=None, **headers):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("POST", "/v1/chat/completions", json.dumps(data), {"Authorization": auth or "Bearer " + token, **headers})
                response = conn.getresponse()
                result = response.status, response.read()
                conn.close()
                return result
            assert request({"model": "fixture-model"}, auth="Bearer denied")[0] == 401
            assert request({"model": "other"})[0] == 403
            assert received == []
            code, data = request({"model": "fixture-model", "stream": streaming, "messages": []}, Cookie="owner-session=deny", Host="evil.invalid")
            assert code == 200 and key.encode() not in data and b"[REDACTED]" in data
            assert received[0][0] == "/v1/chat/completions"
            assert received[0][1]["Authorization"] == "Bearer " + key
            assert "Cookie" not in received[0][1] and received[0][1]["Host"] != "evil.invalid"
            assert received[0][2]["store"] is False
            deadline = time.monotonic() + 2
            while ledger.db.execute("SELECT status FROM requests").fetchone() == (None,) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [(200, 8, 3)]
        ledger.close()
    assert key.encode() not in (tmp_path / "usage.db").read_bytes()


@pytest.mark.parametrize("failure", ["rate-limit", "unavailable", "truncated-stream"])
def test_real_local_failure_preserves_status_and_never_completes_a_truncated_stream(tmp_path, failure):
    class FailingFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = b'data: {"choices":[{"delta":{"content":"unfinished fixture"}}]}\n\n'
            self.send_response(429 if failure == "rate-limit" else 503 if failure == "unavailable" else 200)
            if failure in {"rate-limit", "unavailable"}:
                self.send_header("Retry-After", "17")
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), FailingFixture)) as upstream_port:
        p = ProviderPolicy(policy("local", endpoint=f"http://127.0.0.1:{upstream_port}/v1", api_mode="chat_completions"))
        ledger = UsageLedger(tmp_path / "usage.db")
        token = secrets.token_urlsafe(48)
        with serving(Broker(("127.0.0.1", 0), p, token, Credentials(p, {"api_key": None}), ledger)) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/v1/chat/completions", json.dumps({"model": "fixture-model", "stream": True}),
                         {"Authorization": "Bearer " + token})
            response = conn.getresponse()
            if failure in {"rate-limit", "unavailable"}:
                assert response.status == (429 if failure == "rate-limit" else 503) and b"unfinished fixture" not in response.read()
                assert response.getheader("Retry-After") == "17"
            else:
                assert response.status == 200
                with pytest.raises(http.client.IncompleteRead):
                    response.read()
            conn.close()
        assert ledger.db.execute("SELECT status FROM requests").fetchall() == [(429 if failure == "rate-limit" else 503 if failure == "unavailable" else 502,)]
        ledger.close()


@pytest.mark.parametrize('field,value', [('models', ['unapproved-model']), ('route', 'fallback'),
    ('fallbacks', ['unapproved-provider']), ('model_fallbacks', ['unapproved-model'])])
def test_provider_side_model_routing_cannot_bypass_owner_fallback_authority(field, value):
    with pytest.raises(PermissionError):
        ProviderPolicy(policy('openai', api_mode='chat_completions')).request('/v1/chat/completions',
            {'model': 'fixture-model', field: value})


@pytest.mark.parametrize("thinking", [
    {"include_thoughts": True}, {"include_thoughts": False, "thinking_budget": 0},
    {"include_thoughts": True, "thinking_level": "high"},
])
def test_vertex_native_thinking_body_is_admitted(thinking):
    vertex = ProviderPolicy(policy("vertex", api_mode="chat_completions", endpoint=
        "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"))
    body = {"model": "fixture-model", "messages": [], "extra_body": {"google": {"thinking_config": thinking}}}
    assert vertex.request("/v1/chat/completions", body)["extra_body"] == body["extra_body"]


@pytest.mark.parametrize("extra", [
    {}, {"google": {"thinking_config": {}}},
    {"google": {"thinking_config": {"include_thoughts": 1}}},
    {"google": {"thinking_config": {"thinking_budget": True}}},
    {"google": {"thinking_config": {"thinking_budget": -1}}},
    {"google": {"thinking_config": {"thinking_level": "arbitrary"}}},
    {"google": {"thinking_config": {"extra_headers": {"Authorization": "foreign"}}}},
    {"google": {"thinking_config": {"include_thoughts": True}, "url": "https://foreign.invalid"}},
    {"google": {"thinking_config": {"include_thoughts": True}}, "extra_headers": {}},
])
def test_vertex_cannot_turn_native_thinking_into_an_sdk_override(extra):
    vertex = ProviderPolicy(policy("vertex", api_mode="chat_completions", endpoint=
        "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"))
    with pytest.raises(PermissionError):
        vertex.request("/v1/chat/completions", {"model": "fixture-model", "extra_body": extra})
    with pytest.raises(PermissionError):
        ProviderPolicy(policy("openai", api_mode="chat_completions")).request(
            "/v1/chat/completions", {"model": "fixture-model", "extra_body": extra})


@pytest.mark.parametrize("kind", ["tool_use", "function_call", "response.function_call_arguments.done"])
def test_request_owned_native_tool_aliases_restore_only_dispatch_names(kind):
    from haos.provider_messages import restore
    names = {"hermes_tool_search_2": "tool_search"}
    value = {"type": kind, "name": "hermes_tool_search_2", "arguments": "hermes_tool_search_2",
        "content": {"name": "hermes_tool_search_2"}}
    assert restore(value, names) == {**value, "name": "tool_search"}
    assert value["name"] == "hermes_tool_search_2"
    collision = {"type": kind, "name": "hermes_tool_search"}
    assert restore(collision, names) == collision
    assert restore({"type": "text", "name": "hermes_tool_search_2"}, names) == {
        "type": "text", "name": "hermes_tool_search_2"}


@pytest.mark.parametrize("bad", ["", "f" * 63, "G" * 64, "a" * 65, "a" * 64 + "\n"])
def test_native_moa_stream_refuses_malformed_local_replay_provenance(bad):
    from types import SimpleNamespace
    from haos.provider_moa_streams import _stream_issuer
    with pytest.raises(PermissionError):
        _stream_issuer(SimpleNamespace(response=SimpleNamespace(headers={"X-HAOS-Replay-Binding": bad})))


def test_native_moa_carrier_keeps_opaque_thinking_inside_exact_binding():
    from types import SimpleNamespace
    from haos.provider_moa_streams import _final_delta, _restore, REPLAY_TYPE
    transport = SimpleNamespace(api_mode="anthropic_messages", haos_wire_context=lambda base: ("anthropic", "anthropic_messages", "https://api.anthropic.com"))
    block = {"type": "thinking", "thinking": "public thought", "signature": "fixture-signature"}
    normalized = SimpleNamespace(tool_calls=None, provider_data={"reasoning_details": [block], "anthropic_content_blocks": [block]})
    delta = _final_delta(normalized, transport, "http://127.0.0.1:9120/v1", "primary", "a" * 64)
    assert delta["reasoning_details"] == [{"type": REPLAY_TYPE, "binding": "a" * 64, "data": {"anthropic_content_blocks": [block]}}]
    messages = [{"role": "assistant", "reasoning_details": delta["reasoning_details"]}]
    assert "fixture-signature" not in json.dumps(_restore(messages, "b" * 64))
    assert _restore(messages, "a" * 64)[0]["anthropic_content_blocks"] == [block]
    assert normalized.provider_data["reasoning_details"] == [block]


@pytest.mark.parametrize('mode,container', [('codex_responses', 'output'), ('anthropic_messages', 'content')])
def test_native_response_provenance_is_broker_owned_and_cannot_cross_routes(mode, container):
    from types import SimpleNamespace
    from haos.provider_response_replay import annotate, normalize, FIELD
    from haos.provider_replay import route_binding
    from haos.provider_moa_streams import _restore, REPLAY_TYPE
    policy = SimpleNamespace(provider='local', api_mode=mode, endpoint='http://127.0.0.1:9119/v1')
    source = {container: [{'type': 'reasoning', FIELD: '0' * 64}], FIELD: '0' * 64}
    stamped = annotate(source, policy, 'model-a')
    binding = route_binding(policy, 'model-a')
    assert stamped == {container: [{'type': 'reasoning', FIELD: binding}]}
    assert source[FIELD] == '0' * 64
    native = {'type': 'reasoning', 'encrypted_content': 'opaque-fixture'}
    normalized = SimpleNamespace(provider_data={'codex_reasoning_items': [native]})
    response = SimpleNamespace(**{container: stamped[container]})
    normalize(response, normalized, mode)
    assert normalized.provider_data == {'reasoning_details': [{'type': REPLAY_TYPE, 'binding': binding,
        'data': {'codex_reasoning_items': [native]}}]}
    # Stale raw duplicates never bypass the bound carrier on a foreign route.
    history = [{'role': 'assistant', 'codex_reasoning_items': [native], **normalized.provider_data}]
    for foreign in (route_binding(policy, 'model-b'), route_binding(
            SimpleNamespace(provider='local', api_mode=mode, endpoint='http://127.0.0.1:9121/v1'), 'model-a')):
        assert 'opaque-fixture' not in json.dumps(_restore(history, foreign))
    assert _restore(history, binding)[0]['codex_reasoning_items'] == [native]
    assert history[0]['codex_reasoning_items'] == [native]


@pytest.mark.parametrize('values', [['f' * 63], ['G' * 64], ['a' * 64, 'b' * 64], ['a' * 64 + '\n']])
def test_native_response_rejects_malformed_or_mixed_local_provenance(values):
    from types import SimpleNamespace
    from haos.provider_response_replay import normalize, FIELD
    response = SimpleNamespace(output=[{FIELD: value} for value in values])
    with pytest.raises(PermissionError):
        normalize(response, SimpleNamespace(provider_data={}), 'codex_responses')
