#!/usr/bin/env python3
"""Protocol fixture only: exercises the real upstream subprocess ACP client."""
import json
from pathlib import Path
import sys
import time

base = Path(sys.argv[1])
checks = []
def emit(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)
def response(value):
    emit({"id": request["id"], "result": value})

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        response({"protocolVersion": 1, "agentCapabilities": {"loadSession": False}})
    elif method == "session/new":
        assert request["params"]["mcpServers"] == []
        response({"sessionId": "fixture-session", "configOptions": [{"id": "model", "category": "model",
            "options": [{"value": "fixture-model"}, {"value": "disabled-model", "_meta": {"copilotEnablement": "disabled"}}]}]})
    elif method == "session/set_config_option":
        assert request["params"]["value"] == "fixture-model"
        checks.append("native-model-selection")
        response({})
    elif method == "session/prompt":
        prompt_id = request["id"]
        prompt = request["params"]["prompt"][0]["text"]
        assert "Conversation transcript:" in prompt and "fixture_tool" in prompt
        for index, name in enumerate(("fs/read_text_file", "fs/write_text_file", "terminal/create", "session/request_permission")):
            emit({"id": "denial-" + str(index), "method": name,
                "params": {"path": "/etc/haos/provider-credentials", "content": "must never be written"}})
            denial = json.loads(sys.stdin.readline())
            assert denial["id"] == "denial-" + str(index)
            if name == "session/request_permission":
                assert denial["result"]["outcome"]["outcome"] == "cancelled"
            else:
                assert denial["error"]["code"] == -32601
            checks.append(name + "-denied")
        def delta(text):
            emit({"method": "session/update", "params": {"sessionId": "fixture-session",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})
        delta("early streamed text ")
        deadline = time.monotonic() + 10
        while not (base / "first-delta").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (base / "first-delta").exists(), "first delta must precede the final receipt"
        delta('done <tool_')
        delta('call>{"id":"fixture-call","type":"function","function":{"name":"fixture_tool","arguments":"{}"}}</tool_call>')
        emit({"id": prompt_id, "result": {"stopReason": "end_turn"}})
        (base / "checks.json").write_text(json.dumps(checks))
