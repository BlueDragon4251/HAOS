#!/usr/bin/env python3
"""Actual Google/Azure SDK signing, token HTTP, expiry and cache fixtures."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    tokens = {provider: [secrets.token_urlsafe(40), secrets.token_urlsafe(40)] for provider in ("google", "google-user", "azure")}
    counts = {"google": 0, "google-user": 0, "azure": 0}
    observed = []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def reply(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            assert self.path == "/fixture-tenant/v2.0/.well-known/openid-configuration"
            base = "https://login.microsoftonline.com/fixture-tenant/oauth2/v2.0"
            self.reply({"authorization_endpoint": base + "/authorize", "token_endpoint": base + "/token",
                "issuer": "https://login.microsoftonline.com/fixture-tenant/v2.0",
                "jwks_uri": "https://login.microsoftonline.com/fixture-tenant/discovery/v2.0/keys"})
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if self.path == "/google-token":
                if form["grant_type"] == ["refresh_token"]:
                    assert form["refresh_token"] == ["fixture-private-google-refresh-token"]
                    assert form["client_secret"] == ["fixture-private-google-client-secret"]
                    provider = "google-user"
                else:
                    import jwt
                    claims = jwt.decode(form["assertion"][0], key.public_key(), algorithms=["RS256"],
                        audience="https://oauth2.googleapis.com/token")
                    assert claims["iss"] == "fixture@fixture-project.iam.gserviceaccount.com"
                    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
                    provider = "google"
            else:
                assert self.path == "/fixture-tenant/oauth2/v2.0/token"
                assert form["client_id"] == ["fixture-client"] and form["client_secret"] == ["fixture-private-client-secret"]
                assert form["grant_type"] == ["client_credentials"]
                assert form["scope"] and "azure" in form["scope"][0]
                provider = "azure"
            observed.append((provider, self.path))
            index = min(counts[provider], 1)
            counts[provider] += 1
            self.reply({"access_token": tokens[provider][index], "token_type": "Bearer", "expires_in": 1 if index == 0 else 3600})
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        loopback = "http://127.0.0.1:" + str(port)
        import google.auth
        import azure.identity
        from azure.core.pipeline.transport import RequestsTransport
        original_google = google.auth.load_credentials_from_dict
        original_azure = azure.identity.ClientSecretCredential
        class AzureLoopback(RequestsTransport):
            def send(self, request, **kwargs):
                original = request.url
                parsed = urlsplit(original)
                assert parsed.scheme == "https" and parsed.hostname == "login.microsoftonline.com"
                request.url = loopback + parsed.path + ("?" + parsed.query if parsed.query else "")
                try:
                    return super().send(request, **kwargs)
                finally:
                    request.url = original
        def google_credentials(data, **kwargs):
            credential, project = original_google(data, **kwargs)
            # Keep the actual Google signer and JWT audience; only route the
            # token HTTP destination to this explicit protocol fixture.
            credential._token_uri = loopback + "/google-token"
            return credential, project
        def azure_credentials(**kwargs):
            return original_azure(**kwargs, transport=AzureLoopback(), disable_instance_discovery=True)
        google.auth.load_credentials_from_dict = google_credentials
        azure.identity.ClientSecretCredential = azure_credentials
        try:
            def policy(provider, endpoint):
                return ProviderPolicy({"version": 1, "provider": provider, "endpoint": endpoint,
                    "models": ["fixture"], "default_model": "fixture", "api_mode": "chat_completions",
                    "requests_per_day": 200, "requests_per_minute": 30})
            google_data = {"type": "service_account", "project_id": "fixture-project", "private_key_id": "fixture-key",
                "private_key": pem, "client_email": "fixture@fixture-project.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token"}
            azure_data = {"tenant_id": "fixture-tenant", "client_id": "fixture-client", "client_secret": "fixture-private-client-secret"}
            user_data = {"type": "authorized_user", "client_id": "fixture-google-client",
                "client_secret": "fixture-private-google-client-secret", "refresh_token": "fixture-private-google-refresh-token"}
            for provider, name, data, endpoint in (
                ("vertex", "google", google_data, "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"),
                ("vertex", "google-user", user_data, "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"),
                ("azure-foundry", "azure", azure_data, "https://fixture.services.ai.azure.com/openai/v1")):
                credential = Credentials(policy(provider, endpoint), {"api_key": json.dumps(data)})
                try:
                    headers, redactor = credential.headers()
                    assert headers["Authorization"] == "Bearer " + tokens[name][0]
                    assert tokens[name][0] not in redactor.text(tokens[name][0])
                    headers, redactor = credential.headers()
                    assert headers["Authorization"] == "Bearer " + tokens[name][1] and counts[name] == 2
                    headers, _ = credential.headers()
                    assert headers["Authorization"] == "Bearer " + tokens[name][1] and counts[name] == 2
                    assert tokens[name][1] not in redactor.text(tokens[name][1])
                finally:
                    sdk = credential.cloud_cache.get("credential")
                    if callable(getattr(sdk, "close", None)):
                        sdk.close()
        finally:
            google.auth.load_credentials_from_dict = original_google
            azure.identity.ClientSecretCredential = original_azure
    assert len(observed) == 6
    receipt = {"actual_google_service_account_jwt_signing_refresh_cache": True,
        "actual_google_authorized_user_refresh_cache": True,
        "actual_azure_msal_client_credentials_refresh_cache": True, "actual_loopback_http": True,
        "live_provider_tested": False, "python": sys.version.split()[0],
        "sdk_versions": {name: importlib.metadata.version(name) for name in ("google-auth", "azure-identity", "msal")},
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), root / "haos/provider_cloud.py", root / "haos/provider_proxy.py")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
