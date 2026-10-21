#!/usr/bin/env python3
"""Actual local SDK requests under A→B→A scopes; no provider accounts or inference."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile

from probe_http_provider_matrix import serving, fixture_response


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import httpx
    import openai
    from agent import secret_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from agent.auxiliary_client import CodexAuxiliaryClient
    from haos import provider_policy
    from haos.provider_moa_streams import create_stream
    calls, checks = [], []
    capabilities = {name: secrets.token_urlsafe(48) for name in ("a", "b")}
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v1/responses"
            name = data["model"].removeprefix("model-")
            assert self.headers["Authorization"] == "Bearer " + capabilities[name]
            calls.append(name)
            _result, early, terminal = fixture_response("codex_responses", data["model"], "fixture", data["model"])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for event in [*early, *terminal]:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.close_connection = True
    old_base, old_multiplex = provider_policy.BASE, secret_scope.is_multiplex_active()
    clients = {}
    with tempfile.TemporaryDirectory() as parent, serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        base = f"http://127.0.0.1:{port}/v1"
        provider_policy.BASE = base
        homes = {name: Path(parent) / name for name in capabilities}
        for name, home in homes.items():
            home.mkdir(mode=0o700)
            policy = provider_policy.ProviderPolicy({"version": 1, "provider": "local", "endpoint": base,
                "models": ["model-" + name], "default_model": "model-" + name, "api_mode": "codex_responses",
                "requests_per_day": 200, "requests_per_minute": 120})
            (home / "config.yaml").write_text(json.dumps(policy.client_config()))
            native = openai.OpenAI(api_key=capabilities[name], base_url=base, max_retries=0,
                http_client=httpx.Client(trust_env=False))
            clients[name] = CodexAuxiliaryClient(native, "model-" + name)
        @contextmanager
        def bound(name):
            home_token = set_hermes_home_override(homes[name])
            key_token = secret_scope.set_secret_scope({"HAOS_MODEL_TOKEN": capabilities[name]}, profile_home=str(homes[name]))
            try:
                yield
            finally:
                secret_scope.reset_secret_scope(key_token)
                reset_hermes_home_override(home_token)
        kwargs = lambda name: {"model": "model-" + name, "messages": [{"role": "user", "content": "fixture"}],
            "max_tokens": 64, "tools": [{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}]}
        secret_scope.set_multiplex_active(True)
        try:
            for name in ("a", "b", "a"):
                with bound(name):
                    chunks = list(create_stream(clients[name], kwargs(name)))
                    assert "".join(getattr(c.choices[0].delta, "content", "") for c in chunks) == "model-" + name
                    tool = chunks[-1].choices[0].delta.tool_calls[0]
                    assert tool.function.name == "fixture" and json.loads(tool.function.arguments) == {"x": 1}
                    assert tool.call_id == "call_fixture" and tool.response_item_id
                    before = len(calls)
                    try:
                        create_stream(clients["b" if name == "a" else "a"], kwargs(name))
                    except PermissionError:
                        checks.append("cross-scope-refused")
                    else:
                        raise AssertionError("client capability crossed the profile scope")
                    assert len(calls) == before
            try:
                create_stream(clients["a"], kwargs("a"))
            except secret_scope.UnscopedSecretError:
                checks.append("unscoped-refused")
            else:
                raise AssertionError("multiplex read fell through to process credentials")
            with bound("a"):
                foreign = CodexAuxiliaryClient(openai.OpenAI(api_key=capabilities["a"], base_url="https://unapproved.invalid/v1",
                    max_retries=0, http_client=httpx.Client(trust_env=False)), "model-a")
                try:
                    create_stream(foreign, kwargs("a"))
                except PermissionError:
                    checks.append("foreign-endpoint-refused")
                else:
                    raise AssertionError("foreign endpoint accepted a local capability")
                finally:
                    foreign.close()
            assert calls == ["a", "b", "a"]
        finally:
            provider_policy.BASE = old_base
            secret_scope.set_multiplex_active(old_multiplex)
            for client in clients.values():
                client.close()
    result = {"actual_sdk_profile_sequence": calls, "negative_checks": checks,
        "actual_native_tool_id_and_arguments_preserved": True, "live_provider_tested": False,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__), root / "haos/provider_moa_streams.py")}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"actual_local_sdk_requests": len(calls), "negative_checks": len(checks)}))


if __name__ == "__main__":
    main()
