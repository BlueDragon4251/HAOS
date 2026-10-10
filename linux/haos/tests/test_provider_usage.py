"""Actual SQLite/loopback aggregates, never an external provider/model acceptance."""

import asyncio
import http.client
import json
import secrets
import threading
import time

import pytest

from haos.controller import Controller
from haos.provider_policy import ProviderPolicy
from haos.provider_proxy import Broker, UsageLedger
from haos.provider_usage import UsageSampler, validate_snapshot
from haos.store import MissionStore


def policy():
    return ProviderPolicy({"version": 1, "provider": "openai-codex", "endpoint": "https://chatgpt.com/backend-api/codex",
        "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "codex_responses",
        "requests_per_day": 20, "requests_per_minute": 10})


def test_rolling_usage_survives_restart_and_preserves_missing_receipts(tmp_path):
    p = policy()
    ledger = UsageLedger(tmp_path / "usage.db")
    old = ledger.admit(p, "fixture-model", now=100000 - 86401)
    ledger.finish(old, 200, {"input_tokens": 999, "output_tokens": 999})
    first = ledger.admit(p, "fixture-model", now=100000 - 61)
    ledger.finish(first, 200, {"input_tokens": 5, "output_tokens": 7})
    ledger.admit(p, "fixture-model", now=100000 - 20)
    failed = ledger.admit(p, "fixture-model", now=100000 - 10)
    ledger.finish(failed, 503, {})
    before = validate_snapshot(ledger.snapshot(p, now=100000))
    ledger.close()
    ledger = UsageLedger(tmp_path / "usage.db")
    assert ledger.snapshot(p, now=100000) == before
    assert (before["requests_day"], before["requests_minute"], before["finished_requests_day"], before["unfinished_requests_day"]) == (3, 2, 2, 1)
    assert (before["http_success_day"], before["http_error_day"], before["usage_reported_requests_day"]) == (1, 1, 1)
    assert (before["input_tokens_reported_day"], before["output_tokens_reported_day"]) == (5, 7)
    assert before["cost_available"] is False and before["monetary_cost"] is None
    assert not {"model", "provider", "request_id", "prompt", "response", "credential"} & set(before)
    ledger.close()


def test_missing_and_partial_usage_is_not_invented_as_zero(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.db")
    empty = validate_snapshot(ledger.snapshot(policy()))
    assert empty["requests_day"] == 0 and empty["input_tokens_reported_day"] is None
    request = ledger.admit(policy(), "fixture-model")
    ledger.finish(request, 200, {"input_tokens": 0, "output_tokens": True})
    value = validate_snapshot(ledger.snapshot(policy()))
    assert value["input_tokens_reported_day"] == 0 and value["output_tokens_reported_day"] is None
    assert value["usage_reported_requests_day"] == 0
    ledger.close()


@pytest.mark.parametrize("changes", [
    {"requests_day": True}, {"requests_day": -1}, {"requests_day": 2**53},
    {"snapshot_at": float("nan")}, {"snapshot_at": float("inf")},
    {"input_tokens_reported_day": True}, {"output_tokens_reported_day": -1},
    {"cost_available": True, "monetary_cost": 0}, {"scope": "mission"},
    {"requests_minute": 1}, {"finished_requests_day": 1}, {"usage_reported_requests_day": 1},
    {"authorization": "private value"}, {"requests_per_day": 0},
])
def test_untrusted_usage_receipts_cannot_claim_coverage_cost_or_arbitrary_fields(tmp_path, changes):
    ledger = UsageLedger(tmp_path / "usage.db")
    try:
        value = ledger.snapshot(policy())
        with pytest.raises(ValueError):
            validate_snapshot({**value, **changes})
    finally:
        ledger.close()


def test_real_usage_http_requires_single_capability_and_never_refreshes_credentials_or_calls_a_model(tmp_path, monkeypatch):
    class NoModel:
        def headers(self):
            raise AssertionError("aggregate read must not obtain any provider credential")
    ledger = UsageLedger(tmp_path / "usage.db")
    capability = secrets.token_urlsafe(48)
    broker = Broker(("127.0.0.1", 0), policy(), capability, NoModel(), ledger)
    thread = threading.Thread(target=broker.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr("haos.provider_usage.PORT", broker.server_port)
    try:
        result = UsageSampler(capability).sample()
        assert result["requests_day"] == 0 and result["cost_available"] is False
        assert ledger.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        for path, authorization, extra, expected in [
            ("/v1/haos/usage", [], [], 401),
            ("/v1/haos/usage", ["Bearer invalid"], [], 401),
            ("/v1/haos/usage", ["Bearer " + capability]*2, [], 401),
            ("/v1/haos/usage?history=all", ["Bearer " + capability], [], 405),
            ("/v1/config", ["Bearer " + capability], [], 405),
            ("/v1/haos/usage", ["Bearer " + capability], [("Content-Length", "1")], 400),
            ("/v1/haos/usage", ["Bearer " + capability], [("Content-Length", "0")]*2, 400),
            ("/v1/haos/usage", ["Bearer " + capability], [("Transfer-Encoding", "chunked")], 400),
            ("/v1/haos/usage", ["Bearer " + capability], [], 200),
        ]:
            client = http.client.HTTPConnection("127.0.0.1", broker.server_port, timeout=5)
            client.putrequest("GET", path)
            for value in authorization:
                client.putheader("Authorization", value)
            for key,value in extra:
                client.putheader(key,value)
            client.endheaders()
            response = client.getresponse()
            body = response.read()
            assert response.status == expected
            assert capability.encode() not in body
            if expected == 200:
                assert response.getheader("Cache-Control") == "no-store"
                validate_snapshot(json.loads(body))
            client.close()
    finally:
        broker.shutdown(); broker.server_close(); thread.join(timeout=5)
        ledger.close()


def test_controller_health_reads_aggregates_and_clears_stale_receipts_after_outage(tmp_path, monkeypatch):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        controller = Controller(store, "ws://127.0.0.1:9119/api/ws", set())
        marker = {"requests_day": 2}
        class SystemSampler:
            def sample(self):
                return {"at": time.time(), "status": "ok", "can_dispatch": True, "alerts": [], "errors": []}
        class Usage:
            def sample(self):
                assert controller.provider_usage == marker
                controller.stop.set()
                raise ConnectionError("disposable private credential must never be exposed")
        monkeypatch.setattr("haos.health.HealthSampler", SystemSampler)
        controller.usage_sampler = Usage()
        controller.provider_usage = marker
        await controller.monitor()
        health = await controller.dispatch("uid:1000", {"method": "health"})
        assert health["provider_usage"] is None
        assert health["system"]["status"] == "ok"  # usage failure does not stop the mission controller
        assert store.list() == []
        store.close()
    asyncio.run(exercise())
