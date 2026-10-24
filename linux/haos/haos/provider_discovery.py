"""Model catalogs under private provider identities; never privilege provider code.

Returns bounded public IDs and provenance only. Offline suggestions are never
reported as account entitlement or successful inference.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit, urlencode

from .provider_policy import ProviderPolicy
from .provider_registry import descriptor, default_mode
from .redaction import Redactor

MAX_BODY = 4 * 1024 * 1024
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,511}\Z")
SOURCES = {"provider-api", "sdk-catalog", "upstream-offline", "unavailable"}
DIAGNOSTICS = {"none", "account-required", "catalog-unavailable", "catalog-not-exposed", "publisher-catalog"}


def validate_catalog(data, provider):
    if (not isinstance(data, dict) or set(data) != {"version", "provider", "source", "models", "diagnostic", "inference_tested"}
            or type(data["version"]) is not int or data["version"] != 1 or data["provider"] != provider
            or data["source"] not in SOURCES or data["diagnostic"] not in DIAGNOSTICS
            or data["inference_tested"] is not False or not isinstance(data["models"], list) or len(data["models"]) > 4096):
        raise ValueError("invalid private provider catalog receipt")
    for row in data["models"]:
        if (not isinstance(row, dict) or set(row) != {"id", "api_mode"} or not isinstance(row["id"], str)
                or not MODEL.fullmatch(row["id"]) or any(p in {".", ".."} for p in row["id"].split("/"))
                or row["api_mode"] not in {"chat_completions", "codex_responses", "anthropic_messages"}):
            raise ValueError("unsafe model catalog entry")
    if len({row["id"] for row in data["models"]}) != len(data["models"]):
        raise ValueError("duplicate model catalog entry")
    return data


def receipt(provider, ids, source, diagnostic="none", redactor=None, mode=None):
    redactor = redactor or Redactor()
    values, seen = [], set()
    for value in ids:
        if (not isinstance(value, str) or not MODEL.fullmatch(value)
                or any(p in {".", ".."} for p in value.split("/")) or redactor.text(value) != value):
            continue
        if value not in seen:
            values.append(value)
            seen.add(value)
        if len(values) == 4096:
            break
    return validate_catalog({"version": 1, "provider": provider, "source": source, "diagnostic": diagnostic,
        "models": [{"id": value, "api_mode": mode or default_mode(provider, value)} for value in values],
        "inference_tested": False}, provider)


def fallback(provider, diagnostic, mode=None):
    row = descriptor(provider)
    ids = row["fallback_models"] if row else []
    # The ACP marker means 'use an unspecified CLI default' upstream. HAOS
    # deliberately requires authoritative model selection instead.
    if provider == "copilot-acp":
        ids = []
    return receipt(provider, ids, "upstream-offline" if ids else "unavailable", diagnostic, mode=mode)


def get_json(policy, endpoint, path, headers):
    """No redirect, auth forwarding, TLS override or DNS rebinding on catalogs."""
    parsed = urlsplit(endpoint)
    connection = (http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=8,
                    context=ssl.create_default_context()) if parsed.scheme == "https" else
                  http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=8))
    if policy.provider == "custom":
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise PermissionError("custom catalog resolves outside its public network scope")
        address = addresses[0][4][0]
        connection._create_connection = lambda pair, timeout, source_address=None: socket.create_connection(
            (address, parsed.port or 443), timeout=timeout, source_address=source_address)
    try:
        from .provider_sse import FramedHTTPResponse
        connection.response_class = FramedHTTPResponse
        connection.request("GET", path, headers={"Accept": "application/json", "User-Agent": "HAOS/Hermes-model-catalog", **headers})
        response = connection.getresponse()
        body = response.read(MAX_BODY + 1)
        from .provider_sse import require_complete
        require_complete(response)
        if response.status in {401, 403}:
            raise PermissionError("provider catalog did not return bounded JSON")
        if (len(body) > MAX_BODY or response.getheader("Content-Encoding", "identity") != "identity"
                or response.status != 200 or "json" not in response.getheader("Content-Type", "").lower()):
            raise ValueError("provider catalog did not return bounded JSON")
        return json.loads(body)
    finally:
        connection.close()


def http_catalog(policy, credentials):
    headers, redactor = credentials.headers()
    endpoint = credentials.effective_endpoint
    parsed = urlsplit(endpoint)
    prefix = parsed.path.rstrip("/")
    if policy.provider == "openai-codex":
        from agent.model_metadata import fetch_codex_catalog_entries, CODEX_MODELS_CATALOG_URLS
        from hermes_cli.codex_models import _ranked_slugs
        def fetch(url):
            if url not in CODEX_MODELS_CATALOG_URLS:
                raise PermissionError("unapproved Codex catalog URL")
            path = urlsplit(url)
            data = get_json(policy, endpoint, path.path + "?" + path.query, headers)
            return SimpleNamespace(status_code=200, json=lambda: data)
        entries, _ = fetch_codex_catalog_entries(fetch)
        return receipt(policy.provider, _ranked_slugs(entries), "provider-api", redactor=redactor)
    if policy.provider == "gemini":
        token = headers.pop("Authorization").removeprefix("Bearer ")
        headers["x-goog-api-key"] = token
    if policy.api_mode == "anthropic_messages" and not prefix.endswith("/v1"):
        prefix += "/v1"
    query = dict(credentials.query)
    if policy.provider == "gemini":
        query["pageSize"] = "1000"
    elif policy.api_mode == "anthropic_messages":
        query["limit"] = "1000"
    ids, cursors = [], set()
    for _ in range(5):
        path = prefix + "/models" + (("?" + urlencode(query)) if query else "")
        data = get_json(policy, endpoint, path, headers)
        items = (data if isinstance(data, list) else
                 data.get("models", []) if policy.provider == "gemini" else data.get("data", []))
        if not isinstance(items, list):
            raise ValueError("invalid provider catalog")
        for item in items:
            if not isinstance(item, dict):
                continue
            if policy.provider == "gemini":
                if "generateContent" in item.get("supportedGenerationMethods", []):
                    ids.append(str(item.get("name", "")).removeprefix("models/"))
            elif policy.provider == "copilot":
                from hermes_cli.models import _copilot_text_models
                ids = [m["id"] for m in _copilot_text_models(items)]
                break
            else:
                ids.append(item.get("id"))
        if isinstance(data, dict) and "has_more" in data and type(data["has_more"]) is not bool:
            raise ValueError("invalid provider pagination flag")
        cursor = (data.get("nextPageToken") if policy.provider == "gemini" else
                  data.get("last_id") if isinstance(data, dict) and data.get("has_more") is True else None)
        if isinstance(data, dict) and data.get("has_more") is True and not cursor:
            raise ValueError("provider catalog omitted its required cursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024 or cursor in cursors:
            raise ValueError("invalid/repeated model catalog cursor")
        cursors.add(cursor)
        query["pageToken" if policy.provider == "gemini" else "after_id"] = cursor
    else:
        raise ValueError("provider catalog exceeds its page bound")
    dynamic = policy.provider in {"copilot", "opencode-go", "opencode-zen", "azure-foundry"}
    mode = None if dynamic else policy.api_mode
    if policy.provider == "azure-foundry" and policy.api_mode == "anthropic_messages":
        mode = "anthropic_messages"
    return receipt(policy.provider, ids, "provider-api", redactor=redactor, mode=mode)


def vertex_catalog(policy, credentials):
    """Model Garden's published beta list contract, on the approved region host.

    This lists one publisher's catalogue, not project entitlement or a successful
    OpenAI-compatible inference. No endpoint or resource URL from the response
    controls a follow-up destination.
    """
    model = policy.data['default_model']
    publisher = model.split('/', 1)[0] if '/' in model else 'google'
    if not re.fullmatch('[a-z][a-z0-9-]{0,62}', publisher):
        raise ValueError('unsupported Vertex publisher identity')
    headers, redactor = credentials.headers()
    endpoint = credentials.effective_endpoint
    query = {'pageSize': '1000', 'view': 'PUBLISHER_MODEL_VIEW_BASIC'}
    prefix = 'publishers/' + publisher + '/models/'
    ids, cursors = [], set()
    for _ in range(5):
        data = get_json(policy, endpoint, '/v1beta1/publishers/' + publisher + '/models?' + urlencode(query), headers)
        if not isinstance(data, dict) or not isinstance(data.get('publisherModels', []), list):
            raise ValueError('invalid Vertex publisher catalogue')
        for item in data.get('publisherModels', []):
            name = item.get('name') if isinstance(item, dict) else None
            if isinstance(name, str) and name.startswith(prefix):
                suffix = name[len(prefix):]
                if re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}', suffix):
                    ids.append(publisher + '/' + suffix)
        if len(ids) > 4096:
            raise ValueError('Vertex catalogue exceeds its model bound')
        cursor = data.get('nextPageToken')
        if cursor is None or cursor == '':
            break
        if not isinstance(cursor, str) or len(cursor) > 1024 or cursor in cursors:
            raise ValueError('invalid/repeated Vertex catalogue cursor')
        cursors.add(cursor); query['pageToken'] = cursor
    else:
        raise ValueError('Vertex catalogue exceeds its page bound')
    return receipt(policy.provider, ids, 'provider-api', diagnostic='publisher-catalog', redactor=redactor, mode=policy.api_mode)


def discover(policy, credential):
    if policy.provider == "copilot-acp":
        from .provider_acp import isolated_client
        import tempfile
        with tempfile.TemporaryDirectory(prefix="haos-acp-catalog-") as cwd:
            client = isolated_client(cwd=cwd)
            try:
                return receipt(policy.provider, client.list_models(timeout_seconds=30), "provider-api")
            finally:
                client.close()
    from .provider_proxy import Credentials
    credentials = Credentials(policy, {"api_key": credential})
    try:
        if policy.provider == "vertex":
            return vertex_catalog(policy, credentials)
        if policy.provider == "bedrock":
            from botocore.config import Config
            from .provider_cloud import aws_session
            from agent.bedrock_adapter import _list_foundation_models, _list_inference_profiles
            _, redactor = credentials.headers()
            data = credentials.cloud_data
            region = urlsplit(policy.endpoint).hostname.split(".")[1]
            client = aws_session(data).client("bedrock", region_name=region,
                config=Config(connect_timeout=5, read_timeout=8, retries={"total_max_attempts": 1},
                    **({"signature_version": "bearer"} if "bearer_token" in data else {})))
            try:
                models = []
                class BoundedControl:
                    pages, seen, count = 0, set(), 0
                    def list_foundation_models(self):
                        result = client.list_foundation_models()
                        self.count += len(result.get("modelSummaries", []))
                        if self.count > 4096:
                            raise ValueError("AWS catalog exceeds its bound")
                        return result
                    def list_inference_profiles(self, **kwargs):
                        self.pages += 1
                        if self.pages > 5:
                            raise ValueError("AWS catalog pagination exceeds its bound")
                        result = client.list_inference_profiles(**kwargs)
                        token = result.get("nextToken")
                        if token and token in self.seen:
                            raise ValueError("AWS catalog repeats a cursor")
                        if token:
                            self.seen.add(token)
                        self.count += len(result.get("inferenceProfileSummaries", []))
                        if self.count > 4096:
                            raise ValueError("AWS catalog exceeds its bound")
                        return result
                bounded = BoundedControl()
                _list_foundation_models(bounded, set(), models)
                _list_inference_profiles(bounded, set(), models)
                return receipt(policy.provider, [m["id"] for m in models], "sdk-catalog", redactor=redactor)
            finally:
                client.close()
        return http_catalog(policy, credentials)
    except PermissionError:
        return fallback(policy.provider, "account-required")
    except Exception:
        return fallback(policy.provider, "catalog-unavailable")


def main():
    import contextlib
    import pwd
    value = sys.stdin.buffer.read(32769)
    if len(value) > 32768:
        raise ValueError("model discovery input exceeds its bound")
    request = json.loads(value)
    if not isinstance(request, dict) or set(request) != {"policy", "credential"}:
        raise ValueError("invalid model discovery request")
    policy = ProviderPolicy(request["policy"])
    identity = "haos-provider-acp" if policy.provider == "copilot-acp" else "haos-provider"
    if (os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(identity).pw_uid
            or os.environ.get("HERMES_HOME") != "/var/lib/" + identity + "/.hermes"):
        raise PermissionError("private provider discovery identity required")
    class Discard:
        def write(self, value):
            return len(value)
        def flush(self):
            pass
    # SDK/auth output cannot become public catalog metadata or a journal key.
    with contextlib.redirect_stdout(Discard()), contextlib.redirect_stderr(Discard()):
        result = discover(policy, request["credential"])
    print(json.dumps(validate_catalog(result, policy.provider)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Private provider catalog unavailable; verify account and endpoint.", file=sys.stderr)
        raise SystemExit(1)
