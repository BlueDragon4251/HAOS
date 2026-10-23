"""Native auxiliary streaming over approved local capabilities, never vendor auth."""
from collections import deque
from copy import deepcopy
import hmac
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from .provider_replay import issuer_binding

REPLAY_TYPE = "haos.moa.native_assistant"
REPLAY_FIELDS = ("codex_reasoning_items", "codex_message_items", "anthropic_content_blocks")


def _binding(transport, base, model):
    context = getattr(transport, "haos_wire_context", lambda _: None)(base)
    return issuer_binding(context or [transport.api_mode, base], model)


def _restore(messages, binding):
    output = deepcopy(messages)
    for message in output:
        details = message.get("reasoning_details")
        if not isinstance(details, list):
            continue
        from .provider_response_replay import bind_chat_details
        details = bind_chat_details(details)
        carriers = [item for item in details if isinstance(item, dict) and item.get("type") == REPLAY_TYPE]
        message["reasoning_details"] = [item for item in details if not isinstance(item, dict) or item.get("type") != REPLAY_TYPE]
        if carriers:
            # A bound carrier exclusively owns native replay. Legacy/raw
            # duplicates must not survive when targeting another issuer.
            for key in REPLAY_FIELDS:
                message.pop(key, None)
            message["reasoning_details"] = [item for item in message["reasoning_details"]
                if not isinstance(item, dict) or item.get("type") not in {"thinking", "redacted_thinking"}]
        for item in carriers:
            if item.get("binding") == binding and isinstance(item.get("data"), dict):
                restored = {key: deepcopy(value) for key, value in item["data"].items() if key in REPLAY_FIELDS}
                # The exact broker binding owns provenance. The source SDK may
                # have stamped its own model while normalizing a fallback's
                # output; do not let that stale internal stamp defeat the
                # stronger matching model/endpoint binding on replay.
                for key in ("codex_reasoning_items", "codex_message_items"):
                    if isinstance(restored.get(key), list):
                        restored[key] = [{k: v for k, v in block.items() if k not in {"_issuer_kind", "_issuer_model"}}
                            if isinstance(block, dict) else block for block in restored[key]]
                message.update(restored)
                chat_details = item["data"].get("chat_reasoning_details")
                if isinstance(chat_details, list):
                    message["reasoning_details"].extend(deepcopy(chat_details))
                break
    return output


def _route(client, mode):
    from agent.secret_scope import get_secret
    from hermes_cli.config import load_config_readonly
    from .provider_policy import BASE
    capability = get_secret("HAOS_MODEL_TOKEN", "")
    real_client = getattr(client, "_real_client", client)
    if (not capability or not hmac.compare_digest(str(client.api_key), capability)
            or not hmac.compare_digest(str(real_client.api_key), capability)):
        raise PermissionError("MoA streaming requires its scoped local capability")
    base = str(client.base_url).rstrip("/")
    real = str(real_client.base_url).rstrip("/")
    for row in load_config_readonly().get("providers", {}).values():
        if not isinstance(row, dict) or row.get("key_env") != "HAOS_MODEL_TOKEN" or row.get("api_mode") != mode:
            continue
        candidate = str(row.get("base_url", "")).rstrip("/")
        parsed = urlsplit(candidate)
        actual_urls = {candidate, candidate.removesuffix("/v1")} if mode == "anthropic_messages" else {candidate}
        if (candidate == base and parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.netloc == urlsplit(BASE).netloc and re.fullmatch(r"(?:/routes/[a-z0-9][a-z0-9-]{0,63})?/v1", parsed.path)
                and parsed.port and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and real in actual_urls):
            return candidate
    raise PermissionError("MoA auxiliary client escaped the approved local route")


def _kwargs(transport, supplied, base):
    params = dict(supplied)
    model, messages, tools = params.pop("model"), params.pop("messages"), params.pop("tools", None)
    # Broker transports capture the original carrier before their own restore
    # so an approved fallback can admit its matching target carrier later.
    if not hasattr(transport, "haos_wire_context"):
        messages = _restore(messages, _binding(transport, base, model))
    params["base_url"], params["provider"] = base, "custom"
    params["reasoning_config"] = params.pop("_reasoning_config", params.get("reasoning_config"))
    if params["reasoning_config"] is None and isinstance(params.get("extra_body"), dict):
        params["reasoning_config"] = params["extra_body"].get("reasoning")
    params["max_tokens"] = params.get("max_tokens") or params.get("max_completion_tokens")
    choice = params.get("tool_choice")
    if transport.api_mode == "anthropic_messages" and isinstance(choice, dict):
        params["tool_choice"] = choice.get("function", {}).get("name") if choice.get("type") == "function" else choice.get("type")
    wire = transport.build_kwargs(model, messages, tools, **params)
    wire["stream"] = True
    if supplied.get("timeout") is not None:
        wire["timeout"] = supplied["timeout"]
    return wire


def _chunk(identifier, model, delta, finish=None, usage=None):
    return SimpleNamespace(id=identifier, object="chat.completion.chunk", model=model,
        choices=[SimpleNamespace(index=0, delta=SimpleNamespace(**delta), finish_reason=finish)], usage=usage)


def _usage(value):
    if value is None:
        return None
    incoming, outgoing = getattr(value, "input_tokens", None), getattr(value, "output_tokens", None)
    return SimpleNamespace(prompt_tokens=incoming, completion_tokens=outgoing,
        total_tokens=incoming + outgoing if type(incoming) is int and type(outgoing) is int else None)


def _final_delta(normalized, transport, base, model, issuer=None):
    delta = dict(normalized.provider_data or {})
    replay = {key: delta[key] for key in REPLAY_FIELDS if key in delta}
    if replay:
        public_details = [item for item in delta.get("reasoning_details") or []
            if not isinstance(item, dict) or item.get("type") not in {"thinking", "redacted_thinking"}]
        delta["reasoning_details"] = public_details + [{
            "type": REPLAY_TYPE, "binding": issuer or _binding(transport, base, model), "data": replay}]
    if normalized.tool_calls:
        delta["tool_calls"] = [SimpleNamespace(index=index, id=call.id, type="function",
            function=SimpleNamespace(name=call.name, arguments=call.arguments),
            **(call.provider_data or {})) for index, call in enumerate(normalized.tool_calls)]
    return delta


def _stream_issuer(stream):
    value = stream.response.headers.get("X-HAOS-Replay-Binding")
    if value is not None and not re.fullmatch(r"[a-f0-9]{64}", value):
        raise PermissionError("invalid local broker replay provenance")
    return value


def _responses(client, supplied, base):
    from agent.transports import get_transport
    from agent.codex_runtime import _CodexResponseAssembler
    transport = get_transport("codex_responses")
    wire = _kwargs(transport, supplied, base)
    identifier, pending = "haos-moa-" + uuid.uuid4().hex, deque()
    assembler = _CodexResponseAssembler(model=wire["model"],
        on_text_delta=lambda text: pending.append({"content": text}),
        on_reasoning_delta=lambda text: pending.append({"reasoning_content": text}),
        on_commentary_message=None, on_first_delta=None)
    terminal, usage = False, None
    with client._real_client.with_options(max_retries=0).responses.create(**wire) as stream:
        issuer = _stream_issuer(stream)
        for event in stream:
            assembler.feed(event)
            if getattr(event, "type", None) == "response.completed":
                terminal = True
                usage = getattr(getattr(event, "response", None), "usage", None)
            while pending:
                yield _chunk(identifier, wire["model"], pending.popleft())
        if not terminal:
            raise ConnectionError("MoA Responses stream ended without completion")
        final = assembler.result()
        normalized = transport.normalize_response(final)
        yield _chunk(identifier, wire["model"], _final_delta(normalized, transport, base, supplied["model"], issuer), normalized.finish_reason, _usage(usage))


def _messages(client, supplied, base):
    from agent.transports import get_transport
    transport = get_transport("anthropic_messages")
    wire = _kwargs(transport, supplied, base)
    wire.pop("stream", None)
    identifier, terminal = "haos-moa-" + uuid.uuid4().hex, False
    with client._real_client.with_options(max_retries=0).messages.stream(**wire) as stream:
        issuer = _stream_issuer(stream)
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield _chunk(identifier, wire["model"], {"content": event.delta.text})
                elif event.delta.type == "thinking_delta":
                    yield _chunk(identifier, wire["model"], {"reasoning_content": event.delta.thinking})
            terminal = terminal or event.type == "message_stop"
        if not terminal:
            raise ConnectionError("MoA Messages stream ended without completion")
        final = stream.get_final_message()
        normalized = transport.normalize_response(final)
        yield _chunk(identifier, wire["model"], _final_delta(normalized, transport, base, supplied["model"], issuer), normalized.finish_reason, _usage(final.usage))


def create_stream(client, supplied):
    """Keep Hermes's own fanout/cache planning, replacing only buffered facades."""
    from agent.auxiliary_client import CodexAuxiliaryClient, AnthropicAuxiliaryClient
    if isinstance(client, CodexAuxiliaryClient):
        return _responses(client, supplied, _route(client, "codex_responses"))
    if isinstance(client, AnthropicAuxiliaryClient):
        return _messages(client, supplied, _route(client, "anthropic_messages"))
    return None


def _chat(client, supplied, base):
    from agent.transports import get_transport
    wire = _kwargs(get_transport("chat_completions"), supplied, base)
    wire.setdefault("stream_options", {"include_usage": True})
    terminal = False
    with client.with_options(max_retries=0).chat.completions.create(**wire) as stream:
        for event in stream:
            terminal = terminal or any(choice.finish_reason is not None for choice in event.choices)
            yield event
    if not terminal:
        raise ConnectionError("MoA Chat stream ended without completion")


def create_once(client, supplied, *, stream=False, task=None):
    """One scoped broker call; no secondary SDK/auxiliary retry ladder."""
    from agent.auxiliary_client import _aggregate_chat_stream, _validate_llm_response, _aux_stream_total_ceiling
    chunks = create_stream(client, supplied)
    if chunks is None:
        import openai
        if not isinstance(client, openai.OpenAI):
            raise PermissionError("unsupported scoped MoA SDK client")
        chunks = _chat(client, supplied, _route(client, "chat_completions"))
    if stream:
        return chunks
    result = _aggregate_chat_stream(chunks, model=supplied.get("model", ""), total_ceiling=min(600, _aux_stream_total_ceiling(supplied.get("timeout"))))
    return _validate_llm_response(result, task)
