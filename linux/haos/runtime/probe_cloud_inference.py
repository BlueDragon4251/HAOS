#!/usr/bin/env python3
"""Actual Google/Azure token SDK -> broker -> native model HTTP/SSE fixtures."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

from probe_http_provider_matrix import fixture_response, serving, sdk_stream


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import anthropic
    import azure.identity
    import google.auth
    import httpx
    import openai
    from azure.core.pipeline.transport import RequestsTransport
    from agent.transports import get_transport
    from haos.provider_policy import ProviderPolicy
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_registry import default_mode
    state, observed, token_calls, failures, checks = {}, [], [], [], []
    release, finished = threading.Event(), threading.Event()
    class Ledger(UsageLedger):
        def finish(self, *args):
            super().finish(*args)
            finished.set()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def reply(self, status, value, *, short=False):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data) + (16 if short else 0)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
        def do_GET(self):
            assert self.path == "/fixture-tenant/v2.0/.well-known/openid-configuration"
            base = "https://login.microsoftonline.com/fixture-tenant/oauth2/v2.0"
            self.reply(200, {"authorization_endpoint": base + "/authorize", "token_endpoint": base + "/token",
                "issuer": "https://login.microsoftonline.com/fixture-tenant/v2.0",
                "jwks_uri": "https://login.microsoftonline.com/fixture-tenant/discovery/v2.0/keys"})
        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path in {"/google-token", "/fixture-tenant/oauth2/v2.0/token"}:
                    form = parse_qs(raw.decode())
                    data = state["data"]
                    assert form["client_id"] == [data["client_id"]] and form["client_secret"] == [data["client_secret"]]
                    if self.path == "/google-token":
                        assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == [data["refresh_token"]]
                    else:
                        assert form["grant_type"] == ["client_credentials"] and form["scope"] == ["https://ai.azure.com/.default"]
                    token_calls.append(state["id"])
                    self.reply(200, {"access_token": state["token"], "token_type": "Bearer", "expires_in": 3600})
                    return
                body = json.loads(raw)
                mode, case = state["mode"], state["case"]
                assert self.path == state["path"]
                assert body["model"] == state["wire_model"] and body["tools"]
                assert self.headers["Authorization"] == "Bearer " + state["token"]
                assert not self.headers.get("x-api-key") and not self.headers.get("Cookie")
                assert state["capability"] not in " ".join(self.headers.values())
                observed.append(state["id"] + ":" + case)
                if case in {"401", "429"}:
                    self.reply(int(case), {"error": {"message": state["token"], "type": "fixture_error"}})
                    return
                tool = body["tools"][0]
                result, early, terminal = fixture_response(mode, body["model"],
                    tool.get("name") or tool["function"]["name"], "early fixture " + state["token"])
                if case in {"json", "json-framing"}:
                    self.reply(200, result, short=case == "json-framing")
                    return
                def frame(value):
                    prefix = "event: " + value["type"] + "\n" if mode == "anthropic_messages" else ""
                    return (prefix + "data: " + (value if isinstance(value, str) else json.dumps(value)) + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                if case == "stream-framing":
                    self.send_header("Content-Length", str(sum(len(frame(value)) for value in [*early, *terminal]) + 16))
                self.end_headers()
                for value in early:
                    self.wfile.write(frame(value))
                self.wfile.flush()
                assert release.wait(5), "cloud SDK route did not stream before completion"
                if case != "abort":
                    for value in terminal:
                        self.wfile.write(frame(value))
                self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    old_google, old_azure = google.auth.load_credentials_from_dict, azure.identity.ClientSecretCredential
    old_https = http.client.HTTPSConnection
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as fixture_port:
        loopback = f"http://127.0.0.1:{fixture_port}"
        class AzureHTTP(RequestsTransport):
            def send(self, request, **kwargs):
                original = request.url
                parsed = urlsplit(original)
                assert parsed.scheme == "https" and parsed.hostname == "login.microsoftonline.com"
                request.url = loopback + parsed.path + ("?" + parsed.query if parsed.query else "")
                try:
                    return super().send(request, **kwargs)
                finally:
                    request.url = original
        def google_credentials(data, **kwargs):
            credential, project = old_google(data, **kwargs)
            credential._token_uri = loopback + "/google-token"
            return credential, project
        def model_http(host, port=443, **kwargs):
            assert host == urlsplit(state["endpoint"]).hostname and port == 443
            return http.client.HTTPConnection("127.0.0.1", fixture_port, timeout=kwargs.get("timeout", 5))
        google.auth.load_credentials_from_dict = google_credentials
        azure.identity.ClientSecretCredential = lambda **kwargs: old_azure(**kwargs, transport=AzureHTTP(), disable_instance_discovery=True)
        http.client.HTTPSConnection = model_http
        try:
            for provider, auth, mode in [("vertex", "sdk", "chat_completions"), *[
                    ("azure-foundry", auth, mode) for auth in ("sdk", "api-key")
                    for mode in ("chat_completions", "codex_responses", "anthropic_messages")]]:
                model = {"chat_completions": "phi-fixture", "codex_responses": "gpt-5.4",
                    "anthropic_messages": "anthropic/claude-opus-4.6"}[mode]
                endpoint = ("https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"
                    if provider == "vertex" else "https://fixture.services.ai.azure.com/" + ("anthropic" if mode == "anthropic_messages" else "openai/v1"))
                assert default_mode(provider, model, endpoint) == mode
                policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": endpoint,
                    "models": [model], "default_model": model, "api_mode": mode,
                    "requests_per_day": 200, "requests_per_minute": 120})
                register_profiles(policy.data)
                transport = get_transport(mode)
                body = transport.build_kwargs(model, [{"role": "user", "content": "fixture"}],
                    [{"type": "function", "function": {"name": "fixture", "description": "local tool",
                        "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}}],
                    base_url=policy.client_config()["model"]["base_url"], max_tokens=1024, reasoning_config=None)
                token = secrets.token_urlsafe(40)
                data = ({"type": "authorized_user", "client_id": "fixture-google-client",
                    "client_secret": secrets.token_urlsafe(40), "refresh_token": secrets.token_urlsafe(40)} if provider == "vertex" else
                    {"tenant_id": "fixture-tenant", "client_id": "fixture-client", "client_secret": secrets.token_urlsafe(40)})
                credentials = Credentials(policy, {"api_key": token if auth == "api-key" else json.dumps(data)})
                identifier = provider + ":" + auth + ":" + mode
                path = urlsplit(endpoint).path.rstrip("/")
                if mode == "anthropic_messages" and not path.endswith("/v1"):
                    path += "/v1"
                path += {"chat_completions": "/chat/completions", "codex_responses": "/responses",
                    "anthropic_messages": "/messages?api-version=2025-04-15"}[mode]
                state.update(id=identifier, mode=mode, endpoint=endpoint, token=token, data=data, path=path, wire_model=body["model"])
                try:
                    for case in ("json", "stream", "abort", "401", "429", "json-framing", "stream-framing"):
                        print(identifier + ":" + case, flush=True)
                        capability = secrets.token_urlsafe(48)
                        state.update(case=case, capability=capability)
                        release.clear()
                        finished.clear()
                        with tempfile.TemporaryDirectory() as temp:
                            ledger = Ledger(Path(temp) / "usage.db")
                            with serving(Broker(("127.0.0.1", 0), policy, capability, credentials, ledger)) as port:
                                cls = anthropic.Anthropic if mode == "anthropic_messages" else openai.OpenAI
                                base = f"http://127.0.0.1:{port}" + ("" if mode == "anthropic_messages" else "/v1")
                                with cls(api_key=capability, base_url=base, max_retries=0, timeout=10,
                                        http_client=httpx.Client(trust_env=False)) as client:
                                    call = (client.messages.create if mode == "anthropic_messages" else
                                        client.responses.create if mode == "codex_responses" else client.chat.completions.create)
                                    if case in {"401", "429", "json-framing"}:
                                        try:
                                            call(**body)
                                        except (anthropic.APIStatusError, openai.APIStatusError) as error:
                                            assert error.status_code == (502 if case == "json-framing" else int(case))
                                            assert token not in str(error)
                                        else:
                                            raise AssertionError("cloud route accepted incomplete/rejected response")
                                    elif case == "json":
                                        result = call(**body)
                                        normalized = transport.normalize_response(result)
                                        assert normalized.tool_calls[0].name == "fixture" and json.loads(normalized.tool_calls[0].arguments) == {"x": 1}
                                        assert token not in result.model_dump_json()
                                    else:
                                        interrupted, early = False, False
                                        with sdk_stream(client, mode, call, body, accumulate=case == "stream") as stream:
                                            try:
                                                for value in stream:
                                                    encoded = value.model_dump_json()
                                                    assert token not in encoded and capability not in encoded
                                                    if not early and "early fixture " in encoded:
                                                        assert not release.is_set()
                                                        early = True
                                                        release.set()
                                                if case == "stream" and mode in {"codex_responses", "anthropic_messages"}:
                                                    result = stream.get_final_response() if mode == "codex_responses" else stream.get_final_message()
                                                    normalized = transport.normalize_response(result)
                                                    assert normalized.tool_calls[0].name == "fixture" and json.loads(normalized.tool_calls[0].arguments) == {"x": 1}
                                                    assert normalized.content.startswith("early fixture ") and token not in normalized.content
                                            except httpx.RemoteProtocolError:
                                                interrupted = True
                                        assert early and interrupted == (case != "stream")
                            assert finished.wait(5)
                            expected = (200, 8, 5) if case in {"json", "stream"} else (int(case), None, None) if case in {"401", "429"} else (502, None, None)
                            assert ledger.db.execute("SELECT status,input_tokens,output_tokens FROM requests").fetchall() == [expected]
                            ledger.close()
                        checks.append(identifier + ":" + case)
                    assert token_calls.count(identifier) == (1 if auth == "sdk" else 0)
                finally:
                    credential = credentials.cloud_cache.get("credential")
                    if callable(getattr(credential, "close", None)):
                        credential.close()
        finally:
            release.set()
            google.auth.load_credentials_from_dict, azure.identity.ClientSecretCredential = old_google, old_azure
            http.client.HTTPSConnection = old_https
    assert not failures, failures
    assert len(observed) == len(checks) == 49 and len(set(observed)) == 49
    receipt = {"actual_cloud_token_sdk_broker_model_http_cases": checks, "case_count": len(checks),
        "native_google_authorized_user_and_azure_msal_tokens": True,
        "azure_chat_responses_messages_api_key_and_entra": True, "azure_native_api_version_query": True,
        "continuous_early_stream_and_incomplete_http_rejection": True, "token_cache_reused": True,
        "live_provider_tested": False, "python": sys.version.split()[0], "source_files": [
            {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (Path(__file__).resolve(), root / "runtime/probe_http_provider_matrix.py", root / "haos/provider_cloud.py",
                root / "haos/provider_registry.py", root / "haos/provider_profiles.py", root / "haos/provider_proxy.py", root / "haos/provider_sse.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(checks), "live_provider_tested": False}))


if __name__ == "__main__":
    main()
