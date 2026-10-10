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


@pytest.mark.parametrize("failure", ["rate-limit", "truncated-stream"])
def test_real_local_failure_preserves_status_and_never_completes_a_truncated_stream(tmp_path, failure):
    class FailingFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = b'data: {"choices":[{"delta":{"content":"unfinished fixture"}}]}\n\n'
            self.send_response(429 if failure == "rate-limit" else 200)
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
            if failure == "rate-limit":
                assert response.status == 429 and b"unfinished fixture" not in response.read()
            else:
                assert response.status == 200
                with pytest.raises(http.client.IncompleteRead):
                    response.read()
            conn.close()
        assert ledger.db.execute("SELECT status FROM requests").fetchall() == [(429 if failure == "rate-limit" else 502,)]
        ledger.close()
