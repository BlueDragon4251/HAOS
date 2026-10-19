#!/usr/bin/env python3
"""Actual signed boto3 Converse/EventStream over loopback, not AWS acceptance."""
import http.client
import hashlib
import importlib.metadata
import platform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import struct
import sys
import tempfile
import threading
import zlib
from contextlib import contextmanager


def event_frame(kind, payload):
    headers = bytearray()
    for key, value in ((":message-type", "event"), (":event-type", kind), (":content-type", "application/json")):
        key, value = key.encode(), value.encode()
        headers.extend(bytes([len(key)]) + key + b"\x07" + struct.pack("!H", len(value)) + value)
    body = json.dumps(payload).encode()
    prelude = struct.pack("!II", 16 + len(headers) + len(body), len(headers))
    frame = prelude + struct.pack("!I", zlib.crc32(prelude)) + headers + body
    return frame + struct.pack("!I", zlib.crc32(frame))


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
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_cloud import BedrockClient
    from haos import provider_native
    import boto3
    from botocore.config import Config
    results = []
    for case in ("json-tools", "stream-tools", "truncated", "rate-limit"):
        received, release, final_sent = [], threading.Event(), threading.Event()
        capability, key = secrets.token_urlsafe(48), "fixture-access-id"
        secret, session = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        data = {"access_key_id": key, "secret_access_key": secret, "session_token": session}

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                stream = self.path.endswith("converse-stream")
                if case == "rate-limit":
                    body = json.dumps({"message": session}).encode()
                    self.send_response(429)
                    self.send_header("x-amzn-errortype", "ThrottlingException")
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.amazon.eventstream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(event_frame("messageStart", {"role": "assistant"}))
                    self.wfile.write(event_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "signed fixture"}}))
                    self.wfile.flush()
                    if case == "truncated":
                        return
                    release.wait(5)
                    final_sent.set()
                    for kind, payload in (
                        ("contentBlockStart", {"contentBlockIndex": 1, "start": {"toolUse": {"toolUseId": "fixture-call", "name": "fixture"}}}),
                        ("contentBlockDelta", {"contentBlockIndex": 1, "delta": {"toolUse": {"input": json.dumps({"value": session})}}}),
                        ("contentBlockStop", {"contentBlockIndex": 1}),
                        ("messageStop", {"stopReason": "tool_use"}),
                        ("metadata", {"usage": {"inputTokens": 7, "outputTokens": 4, "totalTokens": 11}, "metrics": {"latencyMs": 1}})):
                        self.wfile.write(event_frame(kind, payload))
                else:
                    body = json.dumps({"output": {"message": {"role": "assistant", "content": [
                        {"toolUse": {"toolUseId": "fixture-call", "name": "fixture", "input": {"value": session}}}]}},
                        "stopReason": "tool_use", "usage": {"inputTokens": 7, "outputTokens": 4, "totalTokens": 11},
                        "metrics": {"latencyMs": 1}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        with tempfile.TemporaryDirectory(prefix="haos-bedrock-probe-") as directory:
            ledger = UsageLedger(Path(directory) / "usage.db")
            policy = ProviderPolicy({"version": 1, "provider": "bedrock", "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com",
                "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "chat_completions",
                "requests_per_day": 20, "requests_per_minute": 10})
            with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
                original = provider_native.create_client
                def create_client(policy, headers, credentials):
                    native = boto3.client("bedrock-runtime", region_name="us-east-1", endpoint_url=f"http://127.0.0.1:{port}",
                        aws_access_key_id=key, aws_secret_access_key=secret, aws_session_token=session,
                        config=Config(retries={"total_max_attempts": 1}, read_timeout=10))
                    return BedrockClient(policy, credentials.cloud_data, client=native)
                provider_native.create_client = create_client
                try:
                    with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": json.dumps(data)}), ledger)) as broker:
                        conn = http.client.HTTPConnection("127.0.0.1", broker, timeout=10)
                        conn.request("POST", "/v1/chat/completions", json.dumps({"model": "fixture-model", "stream": case != "json-tools",
                            "messages": [{"role": "user", "content": "local protocol fixture"}],
                            "tools": [{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}]}),
                            {"Authorization": "Bearer " + capability})
                        response = conn.getresponse()
                        if case == "stream-tools":
                            line = response.readline()
                            assert b"signed fixture" in line and not release.is_set() and not final_sent.is_set()
                            release.set()
                            body = line + response.read()
                        elif case == "truncated":
                            try:
                                response.read()
                                raise AssertionError("truncated Bedrock stream was completed")
                            except http.client.IncompleteRead:
                                body = b""
                        else:
                            release.set()
                            body = response.read()
                        assert response.status == (429 if case == "rate-limit" else 200)
                        assert not any(value.encode() in body for value in (key, secret, session))
                        if case in {"json-tools", "stream-tools"}:
                            assert b"tool_calls" in body
                        conn.close()
                finally:
                    release.set()
                    provider_native.create_client = original
            assert key in received[0][1]["Authorization"] and received[0][1]["Authorization"].startswith("AWS4-HMAC-SHA256 ")
            assert received[0][1]["X-Amz-Security-Token"] == session
            assert received[0][2]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "fixture"
            assert ledger.db.execute("SELECT status FROM requests").fetchone()[0] == (502 if case == "truncated" else 429 if case == "rate-limit" else 200)
            ledger.close()
            results.append(case)
    receipt = {"provider": "bedrock", "actual_boto3_signing_eventstream": True, "actual_loopback_http": True,
               "checks": results, "live_provider_tested": False}
    receipt["python"] = platform.python_version()
    receipt["sdk_versions"] = {name: importlib.metadata.version(name) for name in ['boto3', 'botocore']}
    receipt["source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        Path(__file__), Path(sys.argv[1]) / "haos" / 'provider_cloud.py',
        Path(sys.argv[1]) / "haos/provider_proxy.py", Path(sys.argv[1]) / "haos/provider_policy.py")}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
