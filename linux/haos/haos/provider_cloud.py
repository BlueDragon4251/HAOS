"""Cloud SDK credentials and codecs remain inside the separate provider UID.

Credential JSON is owner-entered and delivered as a private systemd credential;
the agent receives only the existing scoped broker capability.
"""
from __future__ import annotations

import json
import hashlib
import re
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit

CLOUD = frozenset({"bedrock", "vertex", "azure-foundry"})


def valid_endpoint(provider, value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.username or parsed.password
            or parsed.query or parsed.fragment or len(value) > 1024):
        return False
    host = parsed.hostname or ""
    if provider == "bedrock":
        return bool(re.fullmatch(r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com", host) and parsed.path in {"", "/"})
    if provider == "vertex":
        return bool(re.fullmatch(r"[a-z0-9-]+-aiplatform\.googleapis\.com", host) and re.fullmatch(
            r"/v1(?:beta1)?/projects/[a-z0-9][a-z0-9-]{2,62}/locations/[a-z0-9-]+/endpoints/openapi", parsed.path))
    if provider == "azure-foundry":
        return bool(re.fullmatch(r"[a-z0-9-]+\.(?:services\.ai|openai|cognitiveservices|models\.ai)\.azure\.com", host)
                    and re.fullmatch(r"(?:/[A-Za-z0-9_-]+){0,8}", parsed.path))
    return False


def credential_data(provider, value):
    if value is None:
        # Explicit owner choice of this service UID's standard SDK chain.
        return {}
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 16384:
        raise ValueError("invalid cloud credential")
    if provider == "azure-foundry" and not value.lstrip().startswith("{"):
        return {"api_key": value}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("cloud credential must be a JSON object")
    if provider == "bedrock":
        if set(data) - {"access_key_id", "secret_access_key", "session_token", "profile", "bearer_token"}:
            raise ValueError("unsupported AWS credential field")
        if "bearer_token" in data and set(data) != {"bearer_token"}:
            raise ValueError("choose either an AWS bearer token or IAM credentials")
        if "bearer_token" in data and (not isinstance(data["bearer_token"], str) or any(ord(char) < 33 or ord(char) > 126 for char in data["bearer_token"])):
            raise ValueError("invalid AWS bearer token")
        if bool(data.get("access_key_id")) != bool(data.get("secret_access_key")):
            raise ValueError("AWS credentials require the complete access/secret key pair")
    elif provider == "vertex":
        if data.get("type") not in {"service_account", "authorized_user"}:
            raise ValueError("use a Google service account or authorized-user credential")
        if data.get("token_uri", "https://oauth2.googleapis.com/token") != "https://oauth2.googleapis.com/token":
            raise PermissionError("Google token endpoint is fixed")
        if data.get("universe_domain", "googleapis.com") != "googleapis.com":
            raise PermissionError("unsupported Google credential universe")
    elif provider == "azure-foundry":
        if set(data) != {"tenant_id", "client_id", "client_secret"}:
            raise ValueError("Azure service principal requires tenant_id, client_id, client_secret")
        if any(not re.fullmatch(r"[A-Za-z0-9-]{1,128}", data[key]) for key in ("tenant_id", "client_id")):
            raise ValueError("invalid Azure service principal identity")
    else:
        raise ValueError("unsupported cloud provider")
    if any(not isinstance(item, str) or not item or len(item) > 8192 for item in data.values()):
        raise ValueError("invalid cloud credential value")
    return data


def aws_session(data):
    """Per-route SDK identity, without process-global AWS environment changes."""
    import boto3
    options = {key: data[value] for key, value in (("aws_access_key_id", "access_key_id"),
        ("aws_secret_access_key", "secret_access_key"), ("aws_session_token", "session_token"),
        ("profile_name", "profile")) if value in data}
    if "bearer_token" in data:
        from botocore.session import Session
        from botocore.credentials import CredentialResolver
        from botocore.tokens import FrozenAuthToken
        session = Session()
        token = FrozenAuthToken(data["bearer_token"])
        class RouteToken:
            def load_token(self, **kwargs):
                return token if kwargs.get("signing_name") in {None, "bedrock"} else None
        session.register_component("token_provider", RouteToken())
        # Bearer-only routes must not probe another route's IAM/instance chain.
        session.register_component("credential_provider", CredentialResolver([]))
        options["botocore_session"] = session
    return boto3.Session(**options)


def aws_identity(data, cache):
    """Freeze this request's real SDK identity before signing and redaction.

    The private session retains native role/SSO/chain refresh. Downstream SDKs
    receive the same frozen values that this request's redactor knows, so a
    concurrent refresh cannot change its signer behind the response boundary.
    """
    if "bearer_token" in data:
        return dict(data)
    identity = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    if cache.get("aws_identity") != identity:
        session = aws_session(data)
        cache.update(aws_identity=identity, aws_session=session)
    credentials = cache["aws_session"].get_credentials()
    if credentials is None:
        raise PermissionError("AWS IAM credentials are not available for this route")
    frozen = credentials.get_frozen_credentials()
    values = {"access_key_id": frozen.access_key, "secret_access_key": frozen.secret_key}
    if frozen.token:
        values["session_token"] = frozen.token
    return credential_data("bedrock", json.dumps(values))


def mantle_endpoint(endpoint):
    if not valid_endpoint("bedrock", endpoint):
        raise PermissionError("Mantle region must derive from the approved Bedrock endpoint")
    region = urlsplit(endpoint).hostname.split(".")[1]
    return f"https://bedrock-mantle.{region}.api.aws/openai/v1"


def mantle_headers(policy, data, body, headers):
    """Use botocore's actual signer with this route's explicit credential chain."""
    if "bearer_token" in data:
        return {**headers, "Authorization": "Bearer " + data["bearer_token"]}
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    credentials = aws_session(data).get_credentials()
    if credentials is None:
        raise PermissionError("AWS IAM credentials are not available for this route")
    region = urlsplit(policy.endpoint).hostname.split(".")[1]
    request = AWSRequest(method="POST", url=mantle_endpoint(policy.endpoint) + "/responses", data=body, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "bedrock", region).add_auth(request)
    return dict(request.headers.items())


def cloud_headers(policy, data, cache):
    if policy.provider == "bedrock":
        return {}, list(data.values())
    if policy.provider == "vertex":
        import google.auth
        from google.auth.transport.requests import Request
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        if "credential" not in cache:
            cache["credential"] = (google.auth.load_credentials_from_dict(data, scopes=scopes)[0] if data else
                                   google.auth.default(scopes=scopes)[0])
        credential = cache["credential"]
        if not credential.valid:
            credential.refresh(Request())
        token = credential.token
    else:
        if "api_key" in data:
            token = data["api_key"]
        else:
            from azure.identity import ClientSecretCredential, DefaultAzureCredential
            if "credential" not in cache:
                cache["credential"] = ClientSecretCredential(**data) if data else DefaultAzureCredential()
            from agent.azure_identity_adapter import SCOPE_AI_AZURE_DEFAULT
            token = cache["credential"].get_token(SCOPE_AI_AZURE_DEFAULT).token
    if not isinstance(token, str) or not token or len(token) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise PermissionError("invalid cloud SDK token")
    if policy.provider == "azure-foundry" and policy.api_mode == "anthropic_messages":
        from agent.anthropic_adapter import build_anthropic_client
        with build_anthropic_client(token, policy.endpoint) as client:
            headers = {key: value for key, value in client.default_headers.items() if isinstance(value, str)}
            cache["query"] = dict(client.default_query)
        return headers, [token, *data.values()]
    return {"Authorization": "Bearer " + token}, [token, *data.values()]


class BedrockClient:
    """Upstream Converse conversion plus actual botocore signing/EventStream."""
    def __init__(self, policy, data, *, client=None):
        from botocore.config import Config
        region = urlsplit(policy.endpoint).hostname.split(".")[1]
        session = aws_session(data)
        self.client = client or session.client("bedrock-runtime", region_name=region, endpoint_url=policy.endpoint,
            config=Config(connect_timeout=15, read_timeout=180, retries={"total_max_attempts": 1},
                          **({"signature_version": "bearer"} if "bearer_token" in data else {})))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.endpoint = policy.endpoint

    def close(self):
        self.client.close()

    def create(self, *, model, messages=None, tools=None, stream=False, **kwargs):
        from agent.bedrock_adapter import build_converse_kwargs, normalize_converse_response
        from .provider_bedrock_replay import restore, carrier
        request = build_converse_kwargs(model, restore(messages or [], model, self.endpoint), tools, kwargs.get("max_tokens", 4096),
                                        kwargs.get("temperature"), kwargs.get("top_p"),
                                        [kwargs["stop"]] if isinstance(kwargs.get("stop"), str) else kwargs.get("stop"))
        for tool in request.get("toolConfig", {}).get("tools", []):
            spec = tool.get("toolSpec", {})
            if spec.get("description") == "":
                spec.pop("description")  # optional in AWS, empty is rejected by botocore
        choice = kwargs.get("tool_choice")
        if choice == "none":
            request.pop("toolConfig", None)
        elif choice is not None and "toolConfig" in request:
            if choice in ("auto", "required"):
                request["toolConfig"]["toolChoice"] = {"auto" if choice == "auto" else "any": {}}
            elif isinstance(choice, dict) and choice.get("type") == "function":
                request["toolConfig"]["toolChoice"] = {"tool": {"name": choice["function"]["name"]}}
            else:
                raise ValueError("unsupported Bedrock tool choice")
        if not stream:
            raw = self.client.converse(**request)
            result = normalize_converse_response(raw)
            if not all(type(raw.get("usage", {}).get(key)) is int for key in ("inputTokens", "outputTokens")):
                result.usage = None
            message = result.choices[0].message
            if message.bedrock_content_blocks:
                message.reasoning_details = [carrier(message.bedrock_content_blocks, model, self.endpoint)]
            result.id, result.object, result.created = "bedrock-" + uuid.uuid4().hex, "chat.completion", int(time.time())
            return result
        response = self.client.converse_stream(**request)
        stream = response["stream"]
        # urllib3.stream() otherwise waits for its large default read amount,
        # holding small token events until much later or EOF. Preserve the
        # pinned botocore parser/CRC checks, feeding it available bytes via
        # read1 so a model delta reaches the phone/agent immediately.
        from botocore.eventstream import EventStream
        raw = stream._raw_stream
        if not callable(getattr(raw, "read1", None)):
            stream.close()
            raise RuntimeError("installed botocore body lacks bounded available-byte reads")
        class AvailableBody:
            def stream(self):
                while chunk := raw.read1(65536):
                    yield chunk
            def close(self):
                raw.close()
        responsive = EventStream(AvailableBody(), stream._output_shape, stream._parser, stream._operation_name)
        return self.events(responsive, model, self.endpoint)

    @staticmethod
    def events(stream, model, endpoint):
        tools, terminal, identifier, created = {}, False, "bedrock-" + uuid.uuid4().hex, int(time.time())
        recorded, size, final_reason = [], 0, None
        try:
            for event in stream:
                import base64
                size += len(json.dumps(event, default=lambda value: base64.b64encode(value).decode()).encode())
                if size > 32 * 1024 * 1024:
                    raise ValueError("Bedrock replay exceeds broker response bound")
                recorded.append(event)
                if any(key.endswith("Exception") for key in event):
                    raise ConnectionError("Bedrock stream failed")
                delta, finish, usage = {}, None, None
                if start := event.get("contentBlockStart"):
                    index, tool = start["contentBlockIndex"], start.get("start", {}).get("toolUse")
                    if tool:
                        tools[index] = len(tools)
                        delta = {"tool_calls": [{"index": tools[index], "id": tool["toolUseId"], "type": "function",
                                                "function": {"name": tool["name"], "arguments": ""}}]}
                if block := event.get("contentBlockDelta"):
                    value, index = block.get("delta", {}), block["contentBlockIndex"]
                    if "text" in value:
                        delta["content"] = value["text"]
                    if "reasoningContent" in value and "text" in value["reasoningContent"]:
                        delta["reasoning_content"] = value["reasoningContent"]["text"]
                    if "toolUse" in value:
                        if index not in tools:
                            raise ValueError("Bedrock tool delta precedes its start")
                        delta["tool_calls"] = [{"index": tools[index], "function": {"arguments": value["toolUse"]["input"]}}]
                if stop := event.get("messageStop"):
                    from agent.bedrock_adapter import _STOP_REASON_TO_FINISH_REASON
                    final_reason = _STOP_REASON_TO_FINISH_REASON.get(stop["stopReason"], "stop")
                    terminal = True
                if metadata := event.get("metadata"):
                    raw = metadata.get("usage", {})
                    if all(type(raw.get(key)) is int for key in ("inputTokens", "outputTokens")):
                        incoming = sum(raw.get(key, 0) for key in ("inputTokens", "cacheReadInputTokens", "cacheWriteInputTokens"))
                        outgoing = raw["outputTokens"]
                        usage = {"prompt_tokens": incoming, "completion_tokens": outgoing, "total_tokens": incoming + outgoing}
                if delta or finish or usage:
                    yield {"id": identifier, "created": created, "object": "chat.completion.chunk", "model": model,
                           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}] if delta or finish else [],
                           "usage": usage}
            if not terminal:
                raise ConnectionError("Bedrock stream ended without messageStop")
            # Reuse the native ordered accumulator after forwarding each early
            # delta. Its signed/redacted/tool block ordering is authoritative.
            from agent.bedrock_adapter import stream_converse_with_callbacks
            from .provider_bedrock_replay import carrier
            result = stream_converse_with_callbacks({"stream": recorded})
            blocks = result.choices[0].message.bedrock_content_blocks
            details = [carrier(blocks, model, endpoint)] if blocks else []
            yield {"id": identifier, "created": created, "object": "chat.completion.chunk", "model": model,
                   "choices": [{"index": 0, "delta": {"reasoning_details": details}, "finish_reason": final_reason}]}
        finally:
            stream.close()
