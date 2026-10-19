#!/usr/bin/env python3
"""Real pinned Gemini codec + loopback network; fixture, not Google acceptance."""
import http.client
import hashlib
import importlib.metadata
import platform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from contextlib import contextmanager


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
    sys.path.insert(0, sys.argv[1])
    from haos.provider_policy import ProviderPolicy, ENDPOINTS
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos import provider_native
    from agent.gemini_native_adapter import GeminiNativeClient
    checks = []
    for case in ("json-tools", "stream-tools", "truncated", "rate-limit"):
        received, release, final_sent = [], threading.Event(), threading.Event()
        key, capability = secrets.token_urlsafe(40), secrets.token_urlsafe(48)

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                streaming = case != "json-tools"
                first = {"candidates": [{"content": {"parts": [{"text": "native fixture"}]}}]}
                final = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "fixture", "args": {"value": key}},
                                                               "thoughtSignature": "fixture-signature"}]}, "finishReason": "STOP"}],
                         "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 4, "totalTokenCount": 11}}
                body = json.dumps(final).encode()
                if case == "rate-limit":
                    body = json.dumps({"error": {"code": 429, "message": key, "status": "RESOURCE_EXHAUSTED"}}).encode()
                self.send_response(429 if case == "rate-limit" else 200)
                self.send_header("Content-Type", "text/event-stream" if streaming and case != "rate-limit" else "application/json")
                if not streaming or case == "rate-limit":
                    self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if streaming and case != "rate-limit":
                    self.wfile.write(b"data: " + json.dumps(first).encode() + b"\n\n")
                    self.wfile.flush()
                    if case != "truncated":
                        release.wait(5)
                        final_sent.set()
                        self.wfile.write(b"data: " + json.dumps(final).encode() + b"\n\n")
                else:
                    self.wfile.write(body)

        with tempfile.TemporaryDirectory(prefix="haos-native-probe-") as directory:
            ledger = UsageLedger(Path(directory) / "usage.db")
            policy = ProviderPolicy({"version": 1, "provider": "gemini", "endpoint": ENDPOINTS["gemini"],
                                     "models": ["gemini-fixture"], "default_model": "gemini-fixture", "api_mode": "chat_completions",
                                     "requests_per_day": 20, "requests_per_minute": 10})
            with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
                original = provider_native.create_client
                # The production policy remains the exact Google HTTPS URL.
                # Only this test substitutes the client target with loopback.
                provider_native.create_client = lambda policy, headers, credentials: GeminiNativeClient(
                    api_key=headers["Authorization"].removeprefix("Bearer "), base_url=f"http://127.0.0.1:{port}/v1beta")
                try:
                    with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": key}), ledger)) as broker:
                        connection = http.client.HTTPConnection("127.0.0.1", broker, timeout=10)
                        connection.request("POST", "/v1/chat/completions", json.dumps({"model": "gemini-fixture", "stream": case != "json-tools",
                            "messages": [{"role": "user", "content": "Protocol fixture, no live model"}],
                            "tools": [{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}]}),
                            {"Authorization": "Bearer " + capability})
                        response = connection.getresponse()
                        if case == "stream-tools":
                            line = response.readline()
                            assert b"native fixture" in line, "first delta must arrive before the final event"
                            assert not release.is_set() and not final_sent.is_set()
                            release.set()
                            body = line + response.read()
                        elif case == "truncated":
                            try:
                                response.read()
                                raise AssertionError("truncated native stream was falsely completed")
                            except http.client.IncompleteRead:
                                body = b""
                        else:
                            release.set()
                            body = response.read()
                        assert response.status == (429 if case == "rate-limit" else 200)
                        assert key.encode() not in body
                        if case in {"stream-tools", "json-tools"}:
                            assert b"tool_calls" in body and b"fixture-signature" in body
                        if case == "stream-tools":
                            assert b"[DONE]" in body
                        connection.close()
                finally:
                    release.set()
                    provider_native.create_client = original
            assert received[0][1]["x-goog-api-key"] == key
            assert "Authorization" not in received[0][1]
            assert "generateContent" in received[0][0] if case == "json-tools" else "streamGenerateContent" in received[0][0]
            assert received[0][2]["tools"][0]["functionDeclarations"][0]["name"] == "fixture"
            assert ledger.db.execute("SELECT status FROM requests").fetchone()[0] == (502 if case == "truncated" else 429 if case == "rate-limit" else 200)
            ledger.close()
            checks.append(case)
    receipt = {"provider": "gemini", "pinned_native_codec": True, "actual_loopback_http": True,
               "checks": checks, "live_provider_tested": False}
    receipt["python"] = platform.python_version()
    receipt["sdk_versions"] = {name: importlib.metadata.version(name) for name in ['httpx']}
    receipt["source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        Path(__file__), Path(sys.argv[1]) / "haos" / 'provider_native.py',
        Path(sys.argv[1]) / "haos/provider_proxy.py", Path(sys.argv[1]) / "haos/provider_policy.py")}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
