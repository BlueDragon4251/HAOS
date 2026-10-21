"""Actual loopback HTTP/SSE contract probes; no live-provider acceptance claim."""
from contextlib import contextmanager
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading

import pytest

from haos.provider_policy import ProviderPolicy
from haos.provider_registry import default_endpoint, default_mode, http_providers, registry
from haos.provider_routes import ProviderRoutes
from haos.provider_proxy import Broker, Credentials, UsageLedger


def route(provider="local", **changes):
    return {"version": 1, "provider": provider,
            "endpoint": default_endpoint(provider) or "http://127.0.0.1:11434/v1",
            "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": default_mode(provider),
            "requests_per_day": 200, "requests_per_minute": 120, **changes}


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


def test_two_active_upstreams_keep_a_third_admission_bounded_and_undispatched(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    release, two_active, finalized = threading.Event(), threading.Event(), threading.Event()
    lock, received = threading.Lock(), []
    capability = secrets.token_urlsafe(40)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            with lock:
                received.append(self.path)
                if len(received) == 2:
                    two_active.set()
            assert release.wait(5), "concurrency fixture was not released"
            body = json.dumps({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    class FixtureLedger(UsageLedger):
        commits = 0
        def finish(self, *args):
            super().finish(*args)
            with lock:
                self.commits += 1
                if self.commits == 2:
                    finalized.set()
    ledger = FixtureLedger(tmp_path / "usage.db")
    try:
        with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream:
            policy = ProviderPolicy(route(endpoint=f"http://127.0.0.1:{upstream}/v1"))
            with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": None}), ledger)) as port:
                def call():
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    try:
                        conn.request("POST", "/v1/chat/completions", json.dumps({"model": "fixture-model", "messages": []}),
                            {"Authorization": "Bearer " + capability})
                        response = conn.getresponse()
                        return response.status, response.read()
                    finally:
                        conn.close()
                with ThreadPoolExecutor(max_workers=3) as pool:
                    first, second = pool.submit(call), pool.submit(call)
                    try:
                        assert two_active.wait(3)
                        third = pool.submit(call)
                        status, body = third.result(timeout=3)
                        assert status == 429 and b"concurrent model limit" in body
                        assert len(received) == 2, "waiting admission exceeded the two-call provider cap"
                    finally:
                        release.set()
                    assert first.result(timeout=3)[0] == second.result(timeout=3)[0] == 200
                    assert finalized.wait(3)
        assert ledger.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 2
    finally:
        release.set()
        ledger.close()


@pytest.mark.parametrize("provider", sorted(http_providers()))
def test_every_http_profile_has_real_policy_transport_and_no_endpoint_override(provider):
    policy = ProviderPolicy(route(provider))
    mode = policy.api_mode
    path = {"chat_completions": "/v1/chat/completions", "codex_responses": "/v1/responses",
            "anthropic_messages": "/v1/messages"}[mode]
    tool = ({"name": "fixture", "input_schema": {"type": "object"}} if mode == "anthropic_messages" else
            {"type": "function", "function": {"name": "fixture"}})
    assert policy.request(path, {"model": "fixture-model", "tools": [tool]})["tools"] == [tool]
    with pytest.raises(PermissionError):
        ProviderPolicy(route(provider, endpoint="https://attacker.invalid/v1"))
    with pytest.raises(PermissionError):
        policy.request(path, {"model": "fixture-model", "tools": [{"type": "computer_20250124", "name": "computer"}]})


def test_bundled_profiles_are_discovered_without_automatically_admitting_unknown_dialects():
    assert len(registry()) == 53
    assert "commandcode-anthropic" in http_providers()
    assert not {"gemini", "bedrock", "copilot-acp", "moa", "vertex"} & http_providers()
    with pytest.raises(ValueError):
        ProviderPolicy(route("new-plugin", endpoint="https://attacker.invalid/v1", api_mode="chat_completions"))


def test_routes_validate_native_fallbacks_and_keep_credentials_out_of_client_configuration():
    first, second = route("local"), route("openrouter")
    config = {"version": 2, "default": "first", "routes": {"first": first, "second": second},
              "fallbacks": {"first": ["second"]}}
    routes = ProviderRoutes(config)
    assert routes.resolve("/routes/second/v1/chat/completions") == ("second", "/v1/chat/completions")
    client = routes.client_config()
    assert client["providers"]["haos-second"]["base_url"].endswith("/routes/second/v1")
    assert client["providers"]["haos-model"]["default_model"] == "fixture-model"
    for path in ("/routes/absent/v1/chat/completions", "/routes/../v1/chat/completions"):
        with pytest.raises(PermissionError):
            routes.resolve(path)
    for update in ({"default": "missing"}, {"fallbacks": {"first": ["first"]}},
                   {"fallbacks": {"first": ["missing"]}}):
        with pytest.raises(ValueError):
            ProviderRoutes({**config, **update})
    config["routes"]["second"] = route("anthropic")
    with pytest.raises(ValueError):
        ProviderRoutes(config)


@pytest.mark.parametrize("mode", ["chat_completions", "codex_responses", "anthropic_messages"])
@pytest.mark.parametrize("streaming", [False, True])
def test_native_protocols_roundtrip_tools_usage_and_scoped_auth(tmp_path, mode, streaming):
    received = []
    key, token = secrets.token_urlsafe(40), secrets.token_urlsafe(48)

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, dict(self.headers), payload))
            if mode == "anthropic_messages":
                completion = {"type": "message", "role": "assistant", "content": [
                    {"type": "tool_use", "id": "call_1", "name": "fixture", "input": {"value": key}}],
                    "usage": {"input_tokens": 7, "output_tokens": 4}}
                events = [{"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
                          {"type": "content_block_start", "index": 0, "content_block": completion["content"][0]},
                          {"type": "message_delta", "usage": {"output_tokens": 4}}, {"type": "message_stop"}]
            elif mode == "codex_responses":
                completion = {"output": [{"type": "function_call", "name": "fixture", "arguments": json.dumps({"value": key})}],
                              "usage": {"input_tokens": 7, "output_tokens": 4}}
                events = [{"type": "response.completed", "response": completion}]
            else:
                completion = {"choices": [{"message": {"tool_calls": [
                    {"type": "function", "function": {"name": "fixture", "arguments": json.dumps({"value": key})}}]}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 4}}
                events = [completion]
            body = (b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
                    + (b"data: [DONE]\n\n" if mode == "chat_completions" else b"")) if streaming else json.dumps(completion).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        policy = ProviderPolicy(route(endpoint=f"http://127.0.0.1:{port}/v1", api_mode=mode))
        # This fixture supplies native headers; the separate pinned-runtime
        # probe verifies real SDK header construction for each native provider.
        class FixtureCredentials:
            def headers(self):
                from haos.redaction import Redactor
                return {"x-api-key": key}, Redactor([key])
        ledger = UsageLedger(tmp_path / "usage.db")
        with serving(Broker(("127.0.0.1", 0), policy, token, FixtureCredentials(), ledger)) as broker:
            path = {"chat_completions": "/v1/chat/completions", "codex_responses": "/v1/responses",
                    "anthropic_messages": "/v1/messages"}[mode]
            tools = ([{"name": "fixture", "input_schema": {"type": "object"}}] if mode == "anthropic_messages" else
                     [{"type": "function", "name": "fixture", "function": {"name": "fixture"}}])
            conn = http.client.HTTPConnection("127.0.0.1", broker, timeout=5)
            conn.request("POST", path, json.dumps({"model": "fixture-model", "stream": streaming, "tools": tools}),
                         {"x-api-key": token, "Cookie": "not-forwarded"})
            response = conn.getresponse()
            body = response.read()
            assert response.status == 200 and b"fixture" in body and key.encode() not in body
            conn.close()
        assert received[0][0] == path
        assert "Cookie" not in received[0][1] and received[0][2]["tools"] == tools
        assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [(200, 7, 4)]
        ledger.close()


@pytest.mark.parametrize("ambiguous", [False, True])
def test_owner_fallback_receives_only_its_own_key_and_model_and_never_replays_started_stream(tmp_path, ambiguous):
    calls = []
    first_key, second_key = secrets.token_urlsafe(40), secrets.token_urlsafe(40)

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = self.headers.get("Authorization")
            calls.append((key, data["model"]))
            first = key == "Bearer " + first_key
            self.send_response(200 if ambiguous or not first else 503)
            self.send_header("Content-Type", "text/event-stream" if ambiguous else "application/json")
            body = (b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n' if ambiguous else
                    json.dumps({"choices": [], "marker": "fixture"}).encode())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        first = route(endpoint=f"http://127.0.0.1:{port}/v1", models=["first-model"], default_model="first-model")
        second = route(endpoint=f"http://127.0.0.1:{port}/v1", models=["second-model"], default_model="second-model")
        routes = ProviderRoutes({"version": 2, "default": "first", "routes": {"first": first, "second": second},
                                 "fallbacks": {"first": ["second"]}})
        credentials = {"first": Credentials(routes.routes["first"], {"api_key": first_key}),
                       "second": Credentials(routes.routes["second"], {"api_key": second_key})}
        ledger, token = UsageLedger(tmp_path / "usage.db"), secrets.token_urlsafe(48)
        with serving(Broker(("127.0.0.1", 0), routes, token, credentials, ledger)) as broker:
            conn = http.client.HTTPConnection("127.0.0.1", broker, timeout=5)
            conn.request("POST", "/v1/chat/completions", json.dumps({"model": "first-model", "stream": ambiguous}),
                         {"Authorization": "Bearer " + token})
            response = conn.getresponse()
            assert response.status == 200
            if ambiguous:
                with pytest.raises(http.client.IncompleteRead):
                    response.read()
            else:
                assert b"fixture" in response.read()
            conn.close()
        assert calls == [("Bearer " + first_key, "first-model")] + ([] if ambiguous else [
            ("Bearer " + second_key, "second-model")])
        assert ledger.db.execute("SELECT status FROM requests ORDER BY rowid").fetchall() == ([(502,)] if ambiguous else [(503,), (200,)])
        ledger.close()


def test_failed_fallback_credentials_cannot_inherit_another_providers_retry_header(tmp_path):
    received = []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(503)
            self.send_header('Retry-After', '17')
            self.send_header('Content-Length', '0')
            self.end_headers()
    with serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        routes = ProviderRoutes({'version': 2, 'default': 'first', 'routes': {
            'first': route(endpoint=f'http://127.0.0.1:{port}/v1'),
            'second': route('deepseek')}, 'fallbacks': {'first': ['second']}})
        credentials = {name: Credentials(policy, {'api_key': None}) for name, policy in routes.routes.items()}
        ledger, capability = UsageLedger(tmp_path / 'usage.db'), secrets.token_urlsafe(48)
        with serving(Broker(('127.0.0.1', 0), routes, capability, credentials, ledger)) as broker:
            conn = http.client.HTTPConnection('127.0.0.1', broker, timeout=5)
            conn.request('POST', '/v1/chat/completions', json.dumps({'model': 'fixture-model'}),
                {'Authorization': 'Bearer ' + capability})
            response = conn.getresponse()
            assert response.status == 503
            assert response.getheader('Retry-After') is None
            response.read()
            conn.close()
        assert len(received) == 1
        assert ledger.db.execute('SELECT status FROM requests ORDER BY rowid').fetchall() == [(503,), (503,)]
        ledger.close()
