"""Native Claude InvokeModel codec and AWS EventStream inside the broker."""
import json
import time


def create_client(policy, data):
    import anthropic
    from urllib.parse import urlsplit
    from agent.anthropic_adapter import _beta_header, _COMMON_BETAS, _CONTEXT_1M_BETA
    # Reuse the pinned SDK's message/body/binary-event codecs. Auth is selected
    # per route instead of changing the shared broker's AWS environment.
    class RouteClient(anthropic.AnthropicBedrock):
        def _prepare_request(self, request):
            if "bearer_token" in data:
                request.headers["Authorization"] = "Bearer " + data["bearer_token"]
            else:
                super()._prepare_request(request)
    options = {key: data[value] for key, value in (("aws_access_key", "access_key_id"),
        ("aws_secret_key", "secret_access_key"), ("aws_session_token", "session_token"), ("aws_profile", "profile")) if value in data}
    return RouteClient(aws_region=urlsplit(policy.endpoint).hostname.split(".")[1], base_url=policy.endpoint,
        timeout=180, max_retries=0, default_headers=_beta_header([*_COMMON_BETAS, _CONTEXT_1M_BETA]), **options)


def forward(handler, payload, redactor):
    from .provider_native import plain
    from .provider_response_replay import annotate
    from .provider_proxy import MAX_LINE, MAX_OUTPUT
    client = create_client(handler.policy, handler.route_credentials.cloud_data)
    result = None
    try:
        result = client.messages.create(**payload)
        if not payload.get("stream"):
            data = annotate(redactor.clean(plain(result)), handler.policy, handler.native_response_model)
            body = json.dumps(data, ensure_ascii=False).encode()
            if len(body) > MAX_OUTPUT:
                raise ValueError("native Messages response exceeds broker bound")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.forward_started = True
            handler.wfile.write(body)
            return 200, data.get("usage", {})
        iterator = iter(result)
        first = next(iterator)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.forward_started = True
        total, terminal, usage, deadline = 0, False, {}, time.monotonic() + 600
        pending = []
        from itertools import chain
        for raw in chain([first], iterator):
            event = annotate(redactor.clean(plain(raw)), handler.policy, handler.native_response_model)
            kind = event.get("type")
            if kind == "error":
                raise ConnectionError("native Messages stream failed")
            terminal = terminal or kind == "message_stop"
            candidate = event.get("message", event)
            if isinstance(candidate.get("usage"), dict):
                # SDK delta models include optional fields as None. They must
                # not erase the input count reported by message_start.
                usage.update({key: value for key, value in candidate["usage"].items() if value is not None})
            body = ("event: " + kind + "\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
            total += len(body)
            if len(body) > MAX_LINE or total > MAX_OUTPUT or time.monotonic() > deadline:
                raise ValueError("native Messages stream exceeds broker bounds")
            finish = kind == "message_delta" and bool(event.get("delta", {}).get("stop_reason"))
            if pending or terminal or finish:
                pending.append(body)
                continue
            handler.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
            handler.wfile.flush()
        if not terminal:
            raise ConnectionError("native Messages stream ended without message_stop")
        for body in pending:
            handler.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()
        return 200, usage
    except Exception as error:
        status = getattr(error, "status_code", None)
        if status in {429, 503}:
            from .provider_retry import error_retry_seconds
            handler.retry_after = error_retry_seconds(error, redactor)
        if not handler.forward_started and type(status) is int and 400 <= status <= 599:
            return status, {}
        raise
    finally:
        if callable(getattr(result, "close", None)):
            result.close()
        client.close()
