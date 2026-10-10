import asyncio
import json

import pytest

from haos.web_access import DashboardAccess, readable_frame

BACKEND, OBSERVER = "b" * 64, "u" * 64


def invoke(path, *, token=OBSERVER, method="GET", websocket=False, query=b"", headers=(), frames=(), app=None, raw=None):
    scope = {"type": "websocket" if websocket else "http", "path": path,
             "raw_path": raw or path.encode(), "method": method, "client": ("127.0.0.1", 10000),
             "headers": ([(b"x-hermes-session-token", token.encode())] if token is not None else []) + list(headers),
             "query_string": query}
    calls, sent, pending = [], [], list(frames)
    async def receive():
        return pending.pop(0)
    async def send(value):
        sent.append(value)
    async def inner(s, receive, send):
        calls.append(s)
        if s["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"actual_fixture":true}'})
        else:
            await send({"type": "websocket.accept"})
            while pending:
                event = await receive()
                calls.append(event)
                if event["type"] == "websocket.disconnect":
                    break
    asyncio.run(DashboardAccess(app or inner, backend_token=BACKEND, observer_token=OBSERVER)(scope, receive, send))
    return calls, sent


@pytest.mark.parametrize("path,method", [("/api/config", "GET"), ("/api/config", "POST"),
    ("/api/env", "GET"), ("/api/providers/oauth/openai-codex/start", "POST"),
    ("/api/pty", "GET"), ("/api/files", "GET"), ("/api/cron", "POST"),
    ("/api/host/identity", "POST"), ("/api/status/../config", "GET")])
def test_observer_never_reaches_privileged_http_routes(path, method):
    calls, sent = invoke(path, method=method)
    assert calls == [] and sent[0]["status"] == 403
    assert BACKEND not in str(sent) and OBSERVER not in str(sent)


def test_private_controller_retains_its_actual_routes_and_public_health_remains():
    calls, sent = invoke("/api/config", token=BACKEND, method="POST")
    assert calls and sent[0]["status"] == 200
    assert invoke("/api/health", token=None)[1][0]["status"] == 200
    assert invoke("/api/host/identity", token=None)[1][0]["status"] == 401


def test_read_scope_translates_only_after_checking_and_strips_alternative_auth():
    calls, sent = invoke("/api/host/identity", headers=[(b"cookie", b"untrusted"),
                         (b"accept-encoding", b"gzip"), (b"sec-websocket-protocol", b"owner-ticket")])
    assert sent[0]["status"] == 200
    assert (b"x-hermes-session-token", BACKEND.encode()) in calls[0]["headers"]
    assert (b"accept-encoding", b"identity") in calls[0]["headers"]
    assert not any(k in {b"cookie", b"sec-websocket-protocol"} for k, v in calls[0]["headers"])


@pytest.mark.parametrize("query,headers,raw", [(b"token=x&token=x", [], None),
    (b"token=" + BACKEND.encode(), [], None),
    (b"", [(b"x-hermes-session-token", OBSERVER.encode())], None),
    (b"", [], b"/api/%63onfig"), (b"", [], b"/api/host\\identity")])
def test_ambiguous_auth_or_encoded_routes_are_denied(query, headers, raw):
    calls, sent = invoke("/api/host/identity", query=query, headers=headers, raw=raw)
    assert not calls and sent[0]["status"] in {401, 403}


@pytest.mark.parametrize("frame", [
    '{"jsonrpc":"2.0","id":1,"method":"prompt.submit","params":{"prompt":"unsafe"}}',
    '{"jsonrpc":"2.0","id":1,"method":"model.save_key"}',
    '{"jsonrpc":"2.0","id":1,"result":{"choice":"once"}}',
    '{"jsonrpc":"2.0","id":1,"method":"gateway.ping","method":"prompt.submit"}',
    '[{"jsonrpc":"2.0","id":1,"method":"gateway.ping"}]',
    '{"jsonrpc":"2.0","id":true,"method":"gateway.ping"}',
    '{"jsonrpc":"2.0","id":1,"method":"gateway.ping","params":{"x":NaN}}',
    "x" * 131073,
])
def test_rpc_mutations_answers_ambiguous_batches_and_oversize_close_before_dispatch(frame):
    calls, sent = invoke("/api/ws", websocket=True, frames=[{"type": "websocket.receive", "text": frame}])
    assert not readable_frame(frame)
    assert calls[-1]["type"] == "websocket.disconnect"
    assert sent[-1]["code"] == 4403 and "unsafe" not in str(sent)


def test_valid_read_rpc_and_controller_mutation_are_not_changed():
    frame = json.dumps({"jsonrpc": "2.0", "id": "fixture", "method": "session.list", "params": {}})
    assert readable_frame(frame)
    calls, _ = invoke("/api/ws", websocket=True, frames=[{"type": "websocket.receive", "text": frame}])
    assert calls[-1]["text"] == frame
    mutation = json.dumps({"jsonrpc": "2.0", "id": "fixture", "method": "session.create", "params": {}})
    calls, _ = invoke("/api/ws", token=BACKEND, websocket=True,
                      frames=[{"type": "websocket.receive", "text": mutation}])
    assert calls[-1]["text"] == mutation
    assert invoke("/api/pty", websocket=True)[1][0]["code"] == 4403


def test_response_credentials_split_across_chunks_are_redacted_before_publication():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"100"), (b"set-cookie", BACKEND.encode())]})
        await send({"type": "http.response.body", "body": BACKEND[:30].encode(), "more_body": True})
        await send({"type": "http.response.body", "body": BACKEND[30:].encode()})
    _, sent = invoke("/api/status", app=app)
    assert sent[1]["body"] == b"[REDACTED]"
    assert not any(k in {b"content-length", b"set-cookie"} for k, v in sent[0]["headers"])


def test_oversized_or_encoded_response_is_not_partially_published():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x" * (4 * 1024 * 1024 + 1)})
    with pytest.raises(ValueError, match="bound"):
        invoke("/api/status", app=app)
