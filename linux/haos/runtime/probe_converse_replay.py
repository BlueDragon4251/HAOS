#!/usr/bin/env python3
"""Real boto3 binary streams and next-turn signed/redacted Converse replay."""
import base64
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading

from probe_bedrock_provider import event_frame, serving


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_cloud import BedrockClient, aws_session
    from haos.provider_profiles import register_profiles
    from haos.provider_bedrock_replay import TYPE
    from haos import provider_native
    from agent.transports import get_transport
    from agent.reasoning_summaries import append_streamed_reasoning_detail
    from botocore.config import Config
    original = provider_native.create_client
    results, failures = [], []
    opaque = base64.b64encode(b"fixture-opaque-thinking").decode()
    blocks = [{"text": "early fixture"}, {"reasoningContent": {"reasoningText": {"text": "fixture thought", "signature": "fixture-signature"}}},
        {"reasoningContent": {"redactedContent": opaque}}, {"toolUse": {"toolUseId": "fixture-call", "name": "fixture", "input": {"x": 1}}},
        {"text": "after tool fixture"}]
    for auth in ("iam", "bearer"):
        for streaming in (False, True):
            key, secret, bearer = "fixture-access", secrets.token_urlsafe(40), secrets.token_urlsafe(48)
            data = {"access_key_id": key, "secret_access_key": secret} if auth == "iam" else {"bearer_token": bearer}
            release, seen = threading.Event(), []
            policy = ProviderPolicy({"version": 1, "provider": "bedrock", "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com",
                "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "chat_completions",
                "requests_per_day": 200, "requests_per_minute": 30})
            register_profiles(policy.data)
            class Fixture(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def do_POST(self):
                    try:
                        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        if auth == "bearer":
                            assert self.headers["Authorization"] == "Bearer " + bearer
                        else:
                            assert self.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=" + key + "/")
                        if seen:
                            assistant = next(message for message in body["messages"] if message["role"] == "assistant")
                            assert assistant["content"] == blocks, "next turn lost native reasoning/tool block order"
                        seen.append(body)
                        if not self.path.endswith("converse-stream"):
                            response = {"output": {"message": {"role": "assistant", "content": blocks}},
                                "stopReason": "tool_use", "usage": {"inputTokens": 7, "outputTokens": 4}}
                            wire = json.dumps(response).encode()
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(wire)))
                            self.end_headers()
                            self.wfile.write(wire)
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", "application/vnd.amazon.eventstream")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        def event(kind, payload):
                            self.wfile.write(event_frame(kind, payload))
                            self.wfile.flush()
                        event("messageStart", {"role": "assistant"})
                        event("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "early fixture"}})
                        assert release.wait(5), "Converse buffered early output"
                        event("contentBlockStop", {"contentBlockIndex": 0})
                        for value in ({"text": "fixture thought"}, {"signature": "fixture-"}, {"signature": "signature"}):
                            event("contentBlockDelta", {"contentBlockIndex": 1, "delta": {"reasoningContent": value}})
                        event("contentBlockStop", {"contentBlockIndex": 1})
                        event("contentBlockDelta", {"contentBlockIndex": 2, "delta": {"reasoningContent": {"redactedContent": opaque}}})
                        event("contentBlockStop", {"contentBlockIndex": 2})
                        event("contentBlockStart", {"contentBlockIndex": 3, "start": {"toolUse": {"toolUseId": "fixture-call", "name": "fixture"}}})
                        event("contentBlockDelta", {"contentBlockIndex": 3, "delta": {"toolUse": {"input": '{"x":1}'}}})
                        event("contentBlockStop", {"contentBlockIndex": 3})
                        event("contentBlockDelta", {"contentBlockIndex": 4, "delta": {"text": "after tool fixture"}})
                        event("contentBlockStop", {"contentBlockIndex": 4})
                        event("messageStop", {"stopReason": "tool_use"})
                        event("metadata", {"usage": {"inputTokens": 7, "outputTokens": 4}})
                    except BaseException as error:
                        failures.append(type(error).__name__)
                        raise
            with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream:
                def local_client(selected_policy, headers, credentials):
                    native = aws_session(credentials.cloud_data).client("bedrock-runtime", region_name="us-east-1",
                        endpoint_url=f"http://127.0.0.1:{upstream}", config=Config(retries={"total_max_attempts": 1},
                            **({"signature_version": "bearer"} if auth == "bearer" else {})))
                    return BedrockClient(selected_policy, credentials.cloud_data, client=native)
                provider_native.create_client = local_client
                with tempfile.TemporaryDirectory() as temp:
                    ledger = UsageLedger(Path(temp) / "usage.db")
                    capability = secrets.token_urlsafe(48)
                    try:
                        with serving(Broker(("127.0.0.1", 0), policy, capability, Credentials(policy, {"api_key": json.dumps(data)}), ledger)) as port:
                            def request(payload):
                                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                                conn.request("POST", "/v1/chat/completions", json.dumps(payload), {"Authorization": "Bearer " + capability})
                                response = conn.getresponse()
                                if payload.get("stream"):
                                    line = response.readline()
                                    assert b"early fixture" in line and not release.is_set()
                                    release.set()
                                    body = line + response.read()
                                else:
                                    body = response.read()
                                assert response.status == 200 and not any(value.encode() in body for value in (key, secret, bearer))
                                conn.close()
                                return body
                            body = request({"model": "fixture-model", "stream": streaming, "messages": [{"role": "user", "content": "fixture"}]})
                            if streaming:
                                details = []
                                for line in body.splitlines():
                                    if line.startswith(b"data:") and line != b"data: [DONE]":
                                        value = json.loads(line[5:])
                                        for choice in value.get("choices", []):
                                            for detail in choice.get("delta", {}).get("reasoning_details", []):
                                                append_streamed_reasoning_detail(details, detail)
                            else:
                                details = json.loads(body)["choices"][0]["message"]["reasoning_details"]
                            assert any(detail.get("type") == TYPE for detail in details)
                            history = [{"role": "user", "content": "fixture"}, {"role": "assistant", "content": "fixture", "reasoning_details": details},
                                {"role": "user", "content": "follow-up fixture"}]
                            payload = get_transport("chat_completions").build_kwargs("fixture-model", history,
                                base_url=policy.client_config()["model"]["base_url"])
                            request(payload)
                        assert len(seen) == 2
                        assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [(200, 7, 4), (200, 7, 4)]
                    finally:
                        release.set()
                        provider_native.create_client = original
                        ledger.close()
            results.append(auth + (":stream-replay" if streaming else ":json-replay"))
    assert not failures
    receipt = {"actual_signed_or_bearer_boto3_replay_cases": results, "actual_http_requests": 8,
        "ordered_signed_redacted_text_tool_next_turn_replay": True, "actual_hermes_stream_detail_accumulator": True,
        "early_delta_before_upstream_terminal": True, "live_provider_tested": False, "python": sys.version.split()[0],
        "source_files": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in
            (Path(__file__), root / "haos/provider_cloud.py", root / "haos/provider_profiles.py", root / "haos/provider_bedrock_replay.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
