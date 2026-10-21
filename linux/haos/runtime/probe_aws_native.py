#!/usr/bin/env python3
"""Actual per-route AWS signing, Mantle and Claude binary EventStream fixtures."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from probe_bedrock_provider import event_frame


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
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    class FixtureLedger(UsageLedger):
        def __init__(self, *args):
            super().__init__(*args)
            self.finished = threading.Event()
            self.admitted = threading.Event()
        def admit(self, *args):
            result = super().admit(*args)
            self.admitted.set()
            return result
        def finish(self, *args):
            super().finish(*args)
            self.finished.set()
        def close(self):
            if self.admitted.is_set():
                assert self.finished.wait(5), "native AWS writer was still active at fixture teardown"
            super().close()
    from haos.provider_profiles import register_profiles
    from haos import provider_bedrock_messages as messages_bridge
    from agent.transports import get_transport
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials as AWSCredentials
    from agent.bedrock_adapter import bedrock_openai_base_url
    results, failures = [], []
    original_https, original_client = http.client.HTTPSConnection, messages_bridge.create_client
    for family in ("mantle", "claude"):
        for auth in ("iam", "bearer"):
            for case in ("json", "stream", "truncated", "rate-limit", "terminal-framing"):
                release = threading.Event()
                key, secret, session, bearer = "fixture-access-id", secrets.token_urlsafe(40), secrets.token_urlsafe(40), secrets.token_urlsafe(48)
                private = {"access_key_id": key, "secret_access_key": secret, "session_token": session} if auth == "iam" else {"bearer_token": bearer}
                reflected = session if auth == "iam" else bearer
                capability = secrets.token_urlsafe(48)
                endpoint = "https://bedrock-runtime.us-east-1.amazonaws.com"
                host = "bedrock-mantle.us-east-1.api.aws" if family == "mantle" else "bedrock-runtime.us-east-1.amazonaws.com"
                mode = "codex_responses" if family == "mantle" else "anthropic_messages"
                model = "openai.gpt-5.5" if family == "mantle" else "us.anthropic.claude-opus-4-6-v1"
                policy = ProviderPolicy({"version": 1, "provider": "bedrock", "endpoint": endpoint,
                    "models": [model], "default_model": model, "api_mode": mode, "requests_per_day": 200, "requests_per_minute": 30})
                register_profiles(policy.data)
                request = get_transport(mode).build_kwargs(model, [{"role": "user", "content": "fixture"},
                    {"role": "assistant", "content": "previous fixture", "reasoning_details": [
                        {"type": "thinking", "thinking": "fixture thought", "signature": "fixture-signature"}]}],
                    [{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}],
                    max_tokens=2048, base_url=policy.client_config()["model"]["base_url"])
                request["stream"] = case != "json"
                seen = []
                class Fixture(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass
                    def do_POST(self):
                        try:
                            raw = self.rfile.read(int(self.headers["Content-Length"]))
                            body = json.loads(raw)
                            authorization = self.headers["Authorization"]
                            if auth == "bearer":
                                assert authorization == "Bearer " + bearer
                                assert not self.headers.get("X-Amz-Security-Token")
                            else:
                                match = re.fullmatch(r"AWS4-HMAC-SHA256 Credential=([^,]+), SignedHeaders=([^,]+), Signature=([a-f0-9]+)", authorization)
                                assert match and match[1].startswith(key + "/") and "/us-east-1/bedrock/aws4_request" in match[1]
                                headers = {name: self.headers[name] for name in match[2].split(";")}
                                # Preserve the logical HTTPS authority even when
                                # this explicit fixture redirects bytes locally.
                                assert self.headers["Host"] == host
                                signed = AWSRequest(method="POST", url="https://" + host + self.path, data=raw, headers=headers)
                                signed.context["timestamp"] = self.headers["X-Amz-Date"]
                                signer = SigV4Auth(AWSCredentials(key, secret, session), "bedrock", "us-east-1")
                                expected = signer.signature(signer.string_to_sign(signed, signer.canonical_request(signed)), signed)
                                assert hmac.compare_digest(expected, match[3]), "actual SigV4 signature mismatch"
                                assert self.headers["X-Amz-Security-Token"] == session
                            if family == "mantle":
                                assert self.path == urlsplit(bedrock_openai_base_url("us-east-1")).path + "/responses"
                                assert body["model"] == model and body["tools"][0]["name"] == "fixture"
                                assert body["store"] is False
                            else:
                                assert self.path.startswith("/model/" + model + "/invoke")
                                assert body["anthropic_version"] == "bedrock-2023-05-31"
                                assert body["tools"][0]["name"] == "fixture"
                                assert any(block.get("signature") == "fixture-signature" for message in body["messages"]
                                    for block in message["content"] if isinstance(message["content"], list))
                                assert "model" not in body and "stream" not in body
                            seen.append(body)
                            if case == "rate-limit":
                                data = json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": session}}).encode()
                                self.send_response(429)
                                self.send_header("Content-Type", "application/json")
                                self.send_header("x-amzn-errortype", "ThrottlingException")
                                self.send_header("Content-Length", str(len(data)))
                                self.end_headers()
                                self.wfile.write(data)
                                return
                            usage = {"input_tokens": 7, "output_tokens": 4}
                            final = ({"id": "resp_fixture", "object": "response", "model": model, "status": "completed", "usage": usage,
                                "output": [{"type": "function_call", "id": "fc_fixture", "call_id": "fixture-call", "name": "fixture", "arguments": json.dumps({"value": reflected})}]}
                                if family == "mantle" else {"id": "msg_fixture", "type": "message", "role": "assistant", "model": model,
                                "content": [{"type": "tool_use", "id": "fixture-call", "name": "fixture", "input": {"value": reflected}}],
                                "stop_reason": "tool_use", "stop_sequence": None, "usage": usage})
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json" if case == "json" else
                                "text/event-stream" if family == "mantle" else "application/vnd.amazon.eventstream")
                            self.send_header("Connection", "close")
                            if case == "terminal-framing":
                                self.send_header("Transfer-Encoding", "chunked")
                            self.end_headers()
                            if case == "json":
                                self.wfile.write(json.dumps(final).encode())
                                return
                            def event(value):
                                data = json.dumps(value).encode()
                                if family == "mantle":
                                    data = b"data: " + data + b"\n\n"
                                else:
                                    data = event_frame("chunk", {"bytes": base64.b64encode(data).decode()})
                                if case == "terminal-framing":
                                    data = f"{len(data):x}\r\n".encode() + data + b"\r\n"
                                self.wfile.write(data)
                                self.wfile.flush()
                            if family == "mantle":
                                event({"type": "response.output_text.delta", "item_id": "fixture", "output_index": 0, "content_index": 0, "delta": "early fixture"})
                            else:
                                event({"type": "message_start", "message": {**final, "content": [], "stop_reason": None,
                                    "usage": {"input_tokens": 7, "output_tokens": 0}}})
                                event({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                                event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "early fixture"}})
                            if case == "truncated":
                                return
                            assert release.wait(5), "native stream buffered until completion"
                            if family == "mantle":
                                event({"type": "response.output_item.done", "output_index": 0, "item": final["output"][0]})
                                event({"type": "response.completed", "response": final})
                            else:
                                event({"type": "content_block_stop", "index": 0})
                                event({"type": "content_block_start", "index": 1, "content_block": final["content"][0]})
                                event({"type": "content_block_stop", "index": 1})
                                event({"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 4}})
                                event({"type": "message_stop"})
                        except BaseException as error:
                            failures.append(type(error).__name__)
                            raise
                with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream:
                    def local_https(selected_host, port=443, **kwargs):
                        assert selected_host == host and port == 443
                        class Connection(http.client.HTTPConnection):
                            def request(self, method, url, body=None, headers={}, **options):
                                return super().request(method, url, body, {**headers, "Host": selected_host}, **options)
                        return Connection("127.0.0.1", upstream, timeout=10)
                    http.client.HTTPSConnection = local_https
                    def local_messages(selected_policy, data):
                        client = original_client(selected_policy, data)
                        client.base_url = f"http://127.0.0.1:{upstream}"
                        # SDK signer signs the fixture URL; rewrite its logical
                        # URL only for signing so verification uses AWS authority.
                        original_prepare = client._prepare_request
                        def prepare(wire):
                            previous = wire.url
                            import httpx
                            wire.url = httpx.URL("https://" + host + previous.raw_path.decode())
                            wire.headers["Host"] = host
                            try:
                                original_prepare(wire)
                            finally:
                                wire.url = previous
                        client._prepare_request = prepare
                        return client
                    messages_bridge.create_client = local_messages
                    with tempfile.TemporaryDirectory() as temp:
                        ledger = FixtureLedger(Path(temp) / "usage.db")
                        try:
                            with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": json.dumps(private)}), ledger)) as port:
                                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                                path = "/v1/responses" if family == "mantle" else "/v1/messages"
                                conn.request("POST", path, json.dumps(request), {"Authorization": "Bearer " + capability})
                                response = conn.getresponse()
                                if case == "stream":
                                    prefix = b""
                                    while b"early fixture" not in prefix:
                                        line = response.readline()
                                        assert line, "stream ended before early delta"
                                        prefix += line
                                    assert not release.is_set()
                                    release.set()
                                    body = prefix + response.read()
                                elif case in {"truncated", "terminal-framing"}:
                                    release.set()
                                    try:
                                        response.read()
                                        raise AssertionError("native AWS truncation was completed")
                                    except http.client.IncompleteRead as error:
                                        body = error.partial
                                    assert b'event: message_stop' not in body and b'response.completed' not in body
                                    assert b'"stop_reason": "tool_use"' not in body
                                else:
                                    body = response.read()
                                assert response.status == (429 if case == "rate-limit" else 200)
                                assert not any(value.encode() in body for value in (key, secret, session, bearer, capability))
                                if case in {"json", "stream"}:
                                    assert b"fixture-call" in body
                                conn.close()
                            assert ledger.finished.wait(5), "native AWS admission was not durably finalized"
                            status, incoming, outgoing = ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchone()
                            assert status == (502 if case in {"truncated", "terminal-framing"} else 429 if case == "rate-limit" else 200)
                            if case in {"json", "stream"}:
                                assert (incoming, outgoing) == (7, 4)
                        finally:
                            release.set()
                            ledger.close()
                            http.client.HTTPSConnection, messages_bridge.create_client = original_https, original_client
                assert len(seen) == 1
                results.append(family + ":" + auth + ":" + case)
    assert not failures
    receipt = {"actual_native_aws_http_cases": results, "botocore_sigv4_verified_cryptographically": True,
        "mantle_endpoint_and_protocol_derived_from_pinned_rules": True,
        "actual_anthropic_bedrock_binary_eventstream": True, "claude_signed_thinking_replay": True,
        "per_route_iam_and_bearer_no_global_env_changes": True, "early_stream_and_truncation_rate_limit": True,
        "live_provider_tested": False, "python": sys.version.split()[0],
        "source_files": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in
            (Path(__file__), root / "haos/provider_cloud.py", root / "haos/provider_bedrock_messages.py",
             root / "haos/provider_profiles.py", root / "haos/provider_policy.py", root / "haos/provider_proxy.py",
             root / "haos/provider_sse.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
