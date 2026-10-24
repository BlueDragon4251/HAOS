"""Private Qwen device authorization with PKCE; no CLI installation required.

Protocol reference: QwenLM/qwen-code c08007668ce01d9282ea702e95ddbc1f5adf57c9,
packages/core/src/qwen/qwenOAuth2.ts (Apache-2.0). Runtime refresh/storage stay
with the pinned Hermes implementation. Device/access/refresh codes are never
rendered; only the provider's checked user authorization URI/code is shown.
"""
import base64
import hashlib
import http.client
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit, parse_qs

HOST = "chat.qwen.ai"
DEVICE_PATH = "/api/v1/oauth2/device/code"
TOKEN_PATH = "/api/v1/oauth2/token"
SCOPE = "openid profile email model.completion"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"
MAX_BODY = 32768


class QwenLoginError(RuntimeError):
    """Fixed diagnostic codes, never an upstream body or credential."""


def _post(path, data, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QwenLoginError("qwen-device-expired")
    connection = http.client.HTTPSConnection(HOST, 443, timeout=min(20, remaining))
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        if path == DEVICE_PATH:
            headers["x-request-id"] = str(uuid.uuid4())
        connection.request("POST", path, urlencode(data).encode(), headers)
        response = connection.getresponse()
        body = response.read(MAX_BODY + 1)
        if (len(body) > MAX_BODY or response.length not in {None, 0}
                or response.getheader("Content-Encoding", "identity") != "identity"
                or response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"):
            raise QwenLoginError("qwen-device-invalid-response")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise QwenLoginError("qwen-device-invalid-response")
        return response.status, value
    except QwenLoginError:
        raise
    except Exception:
        raise QwenLoginError("qwen-device-network-or-json") from None
    finally:
        connection.close()


def _authorization(value):
    code, device = value.get("user_code"), value.get("device_code")
    uri = value.get("verification_uri_complete")
    if (not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,64}", code)
            or not isinstance(device, str) or not 16 <= len(device) <= 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in device)
            or not isinstance(uri, str) or not 1 <= len(uri) <= 2048):
        raise QwenLoginError("qwen-device-invalid-authorization")
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query, strict_parsing=True)
    if (parsed.scheme != "https" or parsed.netloc != HOST or parsed.path != "/authorize"
            or parsed.fragment or query != {"user_code": [code]}):
        raise QwenLoginError("qwen-device-untrusted-authorization-uri")
    expiry, interval = value.get("expires_in"), value.get("interval", 2)
    if type(expiry) is not int or not 1 <= expiry <= 3600 or type(interval) is not int or not 1 <= interval <= 30:
        raise QwenLoginError("qwen-device-invalid-timing")
    return device, uri, code, expiry, interval


def device_login(*, timeout=600, notify=print):
    """Return validated CLI-shaped tokens only after explicit device approval.

    Existing credentials are untouched on cancellation, denial or network loss.
    The caller persists success under the private provider identity using Hermes.
    Ctrl-C interrupts both the bounded network call and the polling wait.
    """
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError("invalid Qwen authorization timeout")
    from hermes_cli.auth_constants import QWEN_OAUTH_CLIENT_ID, QWEN_OAUTH_TOKEN_URL
    if QWEN_OAUTH_TOKEN_URL != "https://" + HOST + TOKEN_PATH:
        raise QwenLoginError("qwen-device-upstream-contract-changed")
    deadline = time.monotonic() + timeout
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    status, value = _post(DEVICE_PATH, {"client_id": QWEN_OAUTH_CLIENT_ID, "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256"}, deadline)
    if status != 200:
        raise QwenLoginError("qwen-device-request-rejected")
    try:
        device, uri, code, expiry, interval = _authorization(value)
    except (ValueError, TypeError):
        raise QwenLoginError("qwen-device-invalid-authorization") from None
    deadline = min(deadline, time.monotonic() + expiry)
    notify("Open " + uri + " and confirm code " + code + ". Ctrl-C cancels.")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= interval:
            raise QwenLoginError("qwen-device-expired")
        time.sleep(interval)
        status, value = _post(TOKEN_PATH, {"client_id": QWEN_OAUTH_CLIENT_ID,
            "grant_type": GRANT, "device_code": device, "code_verifier": verifier}, deadline)
        if status == 200 and "error" not in value:
            lifetime = value.get("expires_in")
            if type(lifetime) is not int or not 1 <= lifetime <= 7 * 86400:
                raise QwenLoginError("qwen-device-invalid-token-expiry")
            from .provider_auth import qwen_import
            try:
                return qwen_import(json.dumps({"access_token": value.get("access_token"),
                    "refresh_token": value.get("refresh_token"), "token_type": value.get("token_type", "Bearer"),
                    "resource_url": value.get("resource_url", "portal.qwen.ai"),
                    "expiry_date": int(time.time() * 1000) + lifetime * 1000}))
            except (ValueError, TypeError, PermissionError):
                raise QwenLoginError("qwen-device-invalid-token") from None
        error = value.get("error")
        if status == 400 and error == "authorization_pending":
            continue
        if status == 429 and error == "slow_down":
            interval = min(30, interval + 5)
            continue
        if error in {"access_denied", "expired_token"}:
            raise QwenLoginError("qwen-device-" + error)
        raise QwenLoginError("qwen-device-poll-rejected")
