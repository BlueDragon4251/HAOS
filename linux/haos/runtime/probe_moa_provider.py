#!/usr/bin/env python3
"""Actual upstream MoA fanout/aggregation through broker-only loopback routes."""
from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading


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
    from haos.provider_routes import ProviderRoutes
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos import provider_policy, provider_routes
    received = []
    keys = {name: secrets.token_urlsafe(40) for name in ("ref-one", "ref-two", "acting")}
    capability = secrets.token_urlsafe(48)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((data["model"], self.headers.get("Authorization"), data))
            body = json.dumps({"id": "fixture-" + data["model"], "object": "chat.completion", "created": 1, "model": data["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": data["model"] + " response fixture"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    with tempfile.TemporaryDirectory(prefix="haos-moa-probe-") as directory:
        os.environ["HERMES_HOME"] = str(Path(directory) / "hermes")
        os.environ["HAOS_MODEL_TOKEN"] = capability
        Path(os.environ["HERMES_HOME"]).mkdir()
        ledger = UsageLedger(Path(directory) / "usage.db")
        with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream:
            routes = ProviderRoutes({"version": 2, "default": "acting", "routes": {
                name: {"version": 1, "provider": "local", "endpoint": f"http://127.0.0.1:{upstream}/v1", "api_mode": "chat_completions",
                       "models": [name], "default_model": name, "requests_per_day": 200, "requests_per_minute": 120} for name in keys},
                "fallbacks": {}, "ensembles": {"owner-preset": {"references": [{"route": name, "model": name} for name in ("ref-one", "ref-two")],
                "aggregator": {"route": "acting", "model": "acting"}}}, "default_ensemble": "owner-preset"})
            credentials = {name: Credentials(routes.routes[name], {"api_key": key}) for name, key in keys.items()}
            with serving(Broker(("127.0.0.1", 0), routes, capability, credentials, ledger)) as broker:
                old_policy_base, old_routes_base = provider_policy.BASE, provider_routes.BASE
                provider_policy.BASE = provider_routes.BASE = f"http://127.0.0.1:{broker}/v1"
                try:
                    config = routes.client_config()
                    Path(os.environ["HERMES_HOME"], "config.yaml").write_text(json.dumps(config))
                    from haos.provider_profiles import register_profiles
                    register_profiles(routes.data)
                    from hermes_cli.config import load_config
                    from hermes_cli.moa_config import validate_moa_payload
                    from hermes_cli.runtime_provider import resolve_runtime_provider
                    assert not validate_moa_payload(config["moa"])
                    loaded = load_config()
                    assert loaded["moa"]["presets"]["default"]["aggregator"]["provider"] == "custom:haos-acting"
                    runtime = resolve_runtime_provider(requested="moa", target_model="owner-preset")
                    assert runtime["provider"] == "moa"
                    from agent.moa_loop import MoAClient
                    result = MoAClient("owner-preset").chat.completions.create(
                        model="owner-preset", messages=[{"role": "user", "content": "Loopback protocol fixture only"}], stream=False, max_tokens=64)
                    assert result.choices[0].message.content == "acting response fixture"
                finally:
                    provider_policy.BASE, provider_routes.BASE = old_policy_base, old_routes_base
        assert sorted(item[0] for item in received) == sorted(keys)
        assert all(auth == "Bearer " + keys[model] for model, auth, body in received)
        acting = next(body for model, auth, body in received if model == "acting")
        assert "ref-one response fixture" in json.dumps(acting) and "ref-two response fixture" in json.dumps(acting)
        assert all(key not in json.dumps(config) for key in keys.values())
        assert ledger.db.execute("SELECT COUNT(*) FROM requests WHERE status=200").fetchone()[0] == 3
        ledger.close()
    receipt = {"provider": "moa", "actual_upstream_fanout_and_aggregation": True, "broker_bound_requests": 3,
               "private_provider_keys_in_agent_config": False, "live_provider_tested": False}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
