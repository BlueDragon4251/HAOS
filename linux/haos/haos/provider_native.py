"""Pinned SDK adapters running only inside the unprivileged provider broker."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace


def plain(value):
    if isinstance(value, SimpleNamespace):
        return plain(vars(value))
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise ValueError("unsupported native provider response type")


def create_client(policy, headers, credentials=None):
    if policy.provider == "gemini":
        from agent.gemini_native_adapter import GeminiNativeClient
        token = headers["Authorization"].removeprefix("Bearer ")
        return GeminiNativeClient(api_key=token, base_url=policy.endpoint, timeout=180)
    if policy.provider == "bedrock":
        from .provider_cloud import BedrockClient
        return BedrockClient(policy, credentials.cloud_data)
    raise ValueError("unimplemented native provider")


def forward_native(handler, payload, headers, redactor):
    from .provider_proxy import MAX_LINE, MAX_OUTPUT
    client = create_client(handler.policy, headers, handler.route_credentials)
    try:
        request = dict(payload)
        request.pop("store", None)
        request["timeout"] = 180
        result = client.chat.completions.create(**request)
        if payload.get("stream") is not True:
            data = redactor.clean(plain(result))
            body = json.dumps(data).encode()
            if len(body) > MAX_OUTPUT:
                raise ValueError("native provider response exceeds broker bound")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.forward_started = True
            handler.wfile.write(body)
            return 200, data.get("usage", {})
        # Native Gemini's iterator makes a real streaming HTTP request. Read
        # its first event before committing HTTP 200, so credential/rate errors
        # retain their status and owner-authorized fallback remains possible.
        iterator = iter(result)
        first = next(iterator)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.forward_started = True
        total, terminal, usage, deadline = 0, False, {}, time.monotonic() + 600
        def write(data):
            nonlocal total
            total += len(data)
            if len(data) > MAX_LINE or total > MAX_OUTPUT or time.monotonic() > deadline:
                raise ValueError("native provider stream exceeds broker bounds")
            handler.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            handler.wfile.flush()
        from itertools import chain
        for raw in chain([first], iterator):
            event = redactor.clean(plain(raw))
            terminal = terminal or any(choice.get("finish_reason") for choice in event.get("choices", []))
            if isinstance(event.get("usage"), dict):
                usage.update(event["usage"])
            write(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n")
        if not terminal:
            raise ConnectionError("native provider ended without a terminal receipt")
        write(b"data: [DONE]\n\n")
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()
        return 200, usage
    except Exception as error:
        status = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        if type(status) is not int and isinstance(response, dict):
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if response.get("Error", {}).get("Code") in {"ThrottlingException", "TooManyRequestsException"}:
                status = 429
        if not handler.forward_started and type(status) is int and 400 <= status <= 599:
            return status, {}
        raise
    finally:
        client.close()
