#!/usr/bin/env python3
"""Actual HTTP artifact API; explicit persisted-session fixture, no model turn."""
import asyncio
import json
from pathlib import Path
import sys

async def session(base, token, workspace):
    from websockets.asyncio.client import connect
    async with connect(base.replace("http:", "ws:") + "/api/ws?token=" + token,
                       open_timeout=10, max_size=4 * 1024 * 1024, proxy=None) as socket:
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": "haos-runtime-probe",
            "method": "session.create", "params": {"source": "herald_os", "cwd": str(workspace),
            "title": "Disposable HAOS API probe", "close_on_disconnect": True}}))
        async with asyncio.timeout(30):
            async for text in socket:
                for line in text.splitlines():
                    reply = json.loads(line)
                    if reply.get("id") == "haos-runtime-probe":
                        if "error" in reply:
                            raise RuntimeError("real Hermes rejected session.create: " + str(reply["error"].get("code")))
                        result = reply["result"]
                        assert result.get("session_id") and result.get("stored_session_id"), result
                        from haos.hermes import websocket_url
                        from haos.hermes_artifact import ArtifactRefused, read
                        from hermes_state import SessionDB
                        db = SessionDB(workspace.parent / '.hermes' / 'state.db')
                        try:
                            db.create_session(result['stored_session_id'], source='herald_os', cwd=str(workspace))
                        finally:
                            db.close()
                        artifact = workspace / "public-fixture.bin"
                        artifact.write_bytes(b"HAOS disposable artifact fixture\x00\xff")
                        checks = []
                        data = await asyncio.to_thread(read, websocket_url(base, token),
                            result["stored_session_id"], str(artifact), lambda: checks.append(True))
                        assert data == artifact.read_bytes() and len(checks) >= 3
                        from haos.hermes_artifact import MAX_BYTES
                        artifact.write_bytes(b'x' * MAX_BYTES)
                        maximum = await asyncio.to_thread(read, websocket_url(base, token),
                            result['stored_session_id'], str(artifact), lambda: None)
                        assert len(maximum) == MAX_BYTES and maximum == b'x' * MAX_BYTES
                        artifact.write_bytes(b'x' * (MAX_BYTES + 1))
                        try:
                            await asyncio.to_thread(read, websocket_url(base, token),
                                result['stored_session_id'], str(artifact), lambda: None)
                        except ArtifactRefused:
                            pass
                        else:
                            raise AssertionError('oversized native artifact admitted')
                        try:
                            await asyncio.to_thread(read, websocket_url(base, token),
                                "missing-session", str(artifact), lambda: None)
                        except ArtifactRefused:
                            pass
                        else:
                            raise AssertionError("artifact read bypassed session ownership")
                        return {"runtime_session_created": True, "durable_session_created": True,
                                "actual_session_artifact_bytes": True,
                                "artifact_unknown_session_denied": True,
                                "maximum_eight_mib_byte_read": True,
                                "native_oversized_artifact_denied": True}
        raise RuntimeError("real Hermes disconnected without a session receipt")


if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    proof = probe(Path(sys.argv[2]).resolve(strict=True), session_probe=session)
    proof['persisted_session_is_fixture_not_model_turn'] = True
    Path(sys.argv[3]).write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))
