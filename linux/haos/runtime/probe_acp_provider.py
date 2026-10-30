#!/usr/bin/env python3
"""Actual pinned Hermes ACP framing, subprocess, streaming and denial probe."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def official_cli_probe(command):
    """No account required: verify the pinned binary accepts the secured flags."""
    import select
    import subprocess
    from haos.provider_acp import ARGS
    with tempfile.TemporaryDirectory(prefix="haos-official-acp-smoke-") as directory:
        process = subprocess.Popen([command, *ARGS], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=directory,
            env={"HOME": directory, "PATH": "/usr/bin:/bin", "DO_NOT_TRACK": "1", "COPILOT_AUTO_UPDATE": "false"})
        try:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}},
                "clientInfo": {"name": "haos-build-probe", "version": "1"}}}) + "\n")
            process.stdin.flush()
            if not select.select([process.stdout], [], [], 45)[0]:
                raise TimeoutError("pinned Copilot CLI did not initialize secured ACP")
            response = json.loads(process.stdout.readline(1024 * 1024))
            assert response["id"] == 1 and response["result"]["protocolVersion"] == 1
            info = response["result"]["agentInfo"]
            source = json.loads(Path(__file__).with_name("copilot-source.json").read_text())
            assert info["version"] == source["version"]
            return {"version": info["version"], "secured_initialize": True, "account_tested": False}
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.provider_acp import isolated_client, completion_events
    from haos.redaction import Redactor
    payload = {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture prompt"}],
        "tools": [{"type": "function", "function": {"name": "fixture_tool", "parameters": {"type": "object"}}}],
        "stream": True}
    with tempfile.TemporaryDirectory(prefix="haos-acp-probe-") as directory:
        base = Path(directory)
        # The fixture executable is injected only by this test. Production has
        # a fixed immutable command and a separately isolated system identity.
        client = isolated_client(command=sys.executable,
            args=[str(Path(__file__).with_name("acp-fixture.py")), directory], cwd=directory)
        events = []
        def emit(event):
            if any(c.get("delta", {}).get("content", "").startswith("early streamed text") for c in event["choices"]):
                assert not (base / "checks.json").exists()
                (base / "first-delta").touch()
            events.append(event)
        try:
            completion_events(payload, client, Redactor(), emit)
        finally:
            client.close()
        checks = json.loads((base / "checks.json").read_text())
        assert len(checks) == 5 and "native-model-selection" in checks
        text = "".join(choice.get("delta", {}).get("content", "") for event in events for choice in event["choices"])
        assert text == "early streamed text done " and "<tool_call>" not in text
        calls = [call for event in events for choice in event["choices"] for call in choice.get("delta", {}).get("tool_calls", [])]
        assert len(calls) == 1 and calls[0]["function"]["name"] == "fixture_tool"
        assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
        assert all("usage" not in event for event in events)
        # A disabled/unknown model may never fall back to the CLI default.
        client = isolated_client(command=sys.executable,
            args=[str(Path(__file__).with_name("acp-fixture.py")), directory], cwd=directory)
        try:
            try:
                client.chat.completions.create(**{**payload, "model": "disabled-model", "stream": False})
            except PermissionError:
                pass
            else:
                raise AssertionError("unknown/disabled ACP model was silently substituted")
        finally:
            client.close()
    receipt = {"actual_upstream_acp_subprocess": True, "early_stream_before_terminal": True,
        "filesystem_terminal_permission_denials": True, "native_model_selection": True,
        "tool_bridge_codec": True, "unknown_model_refused": True, "live_provider_tested": False,
        "python": sys.version.split()[0], "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), root / "haos/provider_acp.py", Path(__file__).with_name("acp-fixture.py"))}}
    if len(sys.argv) == 4:
        receipt["official_cli"] = official_cli_probe(sys.argv[3])
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
