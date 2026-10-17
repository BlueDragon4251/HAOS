import json

from haos.redaction import REDACTED, Redactor
from haos.store import MissionStore


def test_nested_tool_payloads_credentials_urls_and_private_keys_are_redacted():
    credential = "deliberately generated fixture credential"
    provider = "sk-" + "x" * 24
    private = "-----BEGIN PRIVATE KEY-----\nfixture material\n-----END PRIVATE KEY-----"
    redactor = Redactor([credential])
    cleaned = redactor.clean({"result": {"stdout": f"{credential} {provider} {private}",
                                        "authorization": "Bearer anything",
                                        "url": "https://user:fixture@example.test/repo"},
                              "command": "KEY=allowed API_KEY=fixture-value password='two words'"})
    output = json.dumps(cleaned)
    for forbidden in (credential, provider, "fixture material", "fixture-value", "two words", "user:fixture", "anything"):
        assert forbidden not in output
    assert "KEY=allowed" in output
    assert REDACTED in output


def test_every_persistent_mission_boundary_uses_redaction_and_survives_reopen(tmp_path):
    path = tmp_path / "missions.db"
    credential = "unique-fixture-credential-for-this-test"
    store = MissionStore(path, redactor=Redactor([credential]))
    mid = store.create("uid:1000", "request-1", f"Test {credential}")["id"]
    assert store.create("uid:1000", "request-1", f"Test {credential}")["id"] == mid
    store.claim()
    store.record(mid, {"type": "tool.complete", "payload": {"stdout": credential}}, None)
    store.waiting(mid, {"params": {"token": credential}})
    store.settle(mid, "failed", error=credential, result=credential)
    store.close()
    reopened = MissionStore(path)
    assert credential not in json.dumps(reopened.get(mid))
    assert credential not in json.dumps(reopened.events(mid))
    reopened.close()
    # Verify the bytes on disk as well as the response serializer.
    assert credential.encode() not in path.read_bytes()


def test_redaction_preserves_real_telemetry_and_usage_fields():
    value = {"tool": "terminal", "exit_code": 1, "stderr": "test failed at line 42",
             "input_tokens": 17, "output_tokens": 9, "cost": 0.012,
             "session_id": "session-1", "text": "git status --short"}
    assert Redactor().clean(value) == value


def test_pre_dispatch_provider_errors_are_redacted(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    mid = store.create("uid:1000", "a", "Build")["id"]
    store.claim()
    store.unavailable(mid, "HTTP error Authorization: Bearer fixture-secret")
    assert "fixture-secret" not in json.dumps(store.get(mid))
    assert "fixture-secret" not in json.dumps(store.events(mid))
    store.close()
