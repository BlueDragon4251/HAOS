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
import time
import hashlib


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
    import httpx
    from haos.provider_routes import ProviderRoutes
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos import provider_policy, provider_routes
    class FixtureLedger(UsageLedger):
        def __init__(self, *args):
            super().__init__(*args)
            self.order_lock = threading.Lock()
            self.started, self.committed = 0, 0
            self.finished = threading.Event()
        def finish(self, *args):
            with self.order_lock:
                self.started += 1
                position = self.started
            if position <= 2:
                # Actual complete reference responses can precede local
                # finalization. Exercise that real handoff deterministically.
                time.sleep(0.1)
            super().finish(*args)
            with self.order_lock:
                self.committed += 1
                if self.committed == 3:
                    self.finished.set()
    received = []
    keys = {name: secrets.token_urlsafe(40) for name in ("ref-one", "ref-two", "acting")}
    scenario = sys.argv[3] if len(sys.argv) == 4 else "chat"
    assert scenario in {"chat", "mixed", "stream", "mixed-stream", "mixed-messages-stream", "mixed-stream-abort", "mixed-messages-stream-abort", "reference-disconnect"}
    aborted = scenario.endswith("-abort")
    reference_failed = scenario == "reference-disconnect"
    mixed, final_stream = scenario.startswith("mixed"), "stream" in scenario
    modes = {name: ("anthropic_messages" if name == "ref-one" else "codex_responses" if name == "acting" else
                   "chat_completions") if mixed else "chat_completions" for name in keys}
    if scenario.startswith("mixed-messages-stream"):
        modes["ref-one"], modes["acting"] = "codex_responses", "anthropic_messages"
    release_aggregator, terminal_sent = threading.Event(), threading.Event()
    capability = secrets.token_urlsafe(48)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = data["model"]
            mode = modes[model]
            assert self.path == {"anthropic_messages": "/v1/messages", "codex_responses": "/v1/responses", "chat_completions": "/v1/chat/completions"}[mode]
            authorization = self.headers.get("Authorization") or "Bearer " + self.headers.get("x-api-key", "")
            received.append((model, authorization, data))
            if reference_failed and model == "ref-one":
                import socket
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            result = {"id": "fixture-" + model, "object": "chat.completion", "created": 1, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": data["model"] + " response fixture"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11}}
            if mode == "anthropic_messages":
                result = {"id": "fixture-" + model, "type": "message", "role": "assistant", "model": model,
                    "content": [{"type": "text", "text": model + " response fixture"}], "stop_reason": "end_turn",
                    "stop_sequence": None, "usage": {"input_tokens": 7, "output_tokens": 4}}
            elif mode == "codex_responses":
                result = {"id": "fixture-" + model, "object": "response", "model": model, "status": "completed",
                    "output": [{"id": "msg-fixture", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": model + " response fixture", "annotations": []}]}],
                    "usage": {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11}}
            body = json.dumps(result).encode()
            self.send_response(200)
            if data.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                text = model + " response fixture"
                if mode == "codex_responses":
                    item = result["output"][0]
                    values = [{"type": "response.created", "response": {**result, "status": "in_progress", "output": []}},
                        {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
                        {"type": "response.content_part.added", "item_id": item["id"], "output_index": 0, "content_index": 0,
                            "part": {"type": "output_text", "text": "", "annotations": []}},
                        {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": text},
                        {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "text": text},
                        {"type": "response.content_part.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "part": item["content"][0]},
                        {"type": "response.output_item.done", "output_index": 0, "item": item},
                        {"type": "response.completed", "response": result}]
                elif mode == "anthropic_messages":
                    values = [{"type": "message_start", "message": {**result, "content": [], "stop_reason": None}},
                        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
                        {"type": "content_block_stop", "index": 0},
                        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}},
                        {"type": "message_stop"}]
                else:
                    values = [{**result, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
                        {**result, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}, "[DONE]"]
                if aborted and model == "acting":
                    values = values[:-1]
                for sequence, value in enumerate(values):
                    is_text = (isinstance(value, dict) and (value.get("type") in {"response.output_text.delta", "content_block_delta"}
                        or any(choice.get("delta", {}).get("content") for choice in value.get("choices", []))))
                    if mode == "codex_responses":
                        value["sequence_number"] = sequence
                    prefix = "event: " + value["type"] + "\n" if mode == "anthropic_messages" else ""
                    encoded = value if isinstance(value, str) else json.dumps(value)
                    self.wfile.write((prefix + "data: " + encoded + "\n\n").encode())
                    self.wfile.flush()
                    if final_stream and model == "acting" and is_text:
                        assert release_aggregator.wait(5), "MoA buffered the aggregator until completion"
                        terminal_sent.set()
                self.close_connection = True
                return
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    with tempfile.TemporaryDirectory(prefix="haos-moa-probe-") as directory:
        os.environ["HERMES_HOME"] = str(Path(directory) / "hermes")
        os.environ["HAOS_MODEL_TOKEN"] = capability
        Path(os.environ["HERMES_HOME"]).mkdir()
        ledger = FixtureLedger(Path(directory) / "usage.db")
        with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as upstream:
            routes = ProviderRoutes({"version": 2, "default": "acting", "routes": {
                name: {"version": 1, "provider": "local", "endpoint": f"http://127.0.0.1:{upstream}/v1", "api_mode": modes[name],
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
                        model="owner-preset", messages=[{"role": "user", "content": "Loopback protocol fixture only"}], stream=final_stream, max_tokens=64)
                    if final_stream:
                        parts, finished = [], False
                        failure = None
                        try:
                            for chunk in result:
                                for choice in chunk.choices:
                                    text = getattr(choice.delta, "content", None)
                                    if text:
                                        if not parts:
                                            assert not release_aggregator.is_set() and not terminal_sent.is_set()
                                            release_aggregator.set()
                                        parts.append(text)
                                    finished = finished or bool(choice.finish_reason)
                        except (ConnectionError, RuntimeError, httpx.RemoteProtocolError) as exc:
                            failure = exc
                        assert "".join(parts) == "acting response fixture"
                        if aborted:
                            assert failure is not None and not finished, "unfinished stream reported completion"
                        else:
                            assert failure is None and finished
                    else:
                        assert result.choices[0].message.content == "acting response fixture"
                finally:
                    release_aggregator.set()
                    provider_policy.BASE, provider_routes.BASE = old_policy_base, old_routes_base
        assert sorted(item[0] for item in received) == sorted(keys)
        assert all(auth == "Bearer " + keys[model] for model, auth, body in received)
        acting = next(body for model, auth, body in received if model == "acting")
        assert "ref-two response fixture" in json.dumps(acting)
        assert ("ref-one response fixture" in json.dumps(acting)) is not reference_failed
        assert all(key not in json.dumps(config) for key in keys.values())
        assert ledger.finished.wait(5), "MoA admissions were not durably finalized"
        assert ledger.db.execute("SELECT COUNT(*) FROM requests WHERE status=200").fetchone()[0] == (2 if aborted or reference_failed else 3)
        if aborted or reference_failed:
            assert ledger.db.execute("SELECT COUNT(*) FROM requests WHERE status=502").fetchone()[0] == 1
        ledger.close()
    receipt = {"provider": "moa", "actual_upstream_fanout_and_aggregation": True, "broker_bound_requests": 3,
               "private_provider_keys_in_agent_config": False, "live_provider_tested": False,
               "derived_auxiliary_client_sha256": hashlib.sha256(Path(sys.modules["agent.auxiliary_client"].__file__).read_bytes()).hexdigest(),
               "delayed_reference_finalization_handoff": True,
               "native_protocols_by_route": modes,
               "ambiguous_reference_not_replayed": reference_failed,
               "outer_stream": final_stream, "aborted_native_stream_refused": aborted, "first_aggregator_delta_before_terminal": final_stream,
               "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (
                   Path(__file__), Path(sys.argv[1]) / "haos/provider_proxy.py",
                   Path(sys.argv[1]) / "haos/provider_moa_streams.py", Path(sys.argv[1]) / "haos/provider_profiles.py",
                   Path(__file__).with_name("prepare.py"), Path(__file__).with_name("source.json"))}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
