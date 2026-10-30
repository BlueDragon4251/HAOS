#!/usr/bin/env python3
"""Apply reviewed dependency and scoped auxiliary overlays to one exact snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def patch_auxiliary(upstream, expected_sha256, *, check_only=False):
    path = upstream / "agent/auxiliary_client.py"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("auxiliary overlay belongs to another Hermes source")
    anchor = '    # Streaming path (MoA aggregator): return the raw SDK stream, skipping validation and\n'
    addition = '    if task in {"moa_reference", "moa_aggregator"} and str(provider or "").startswith("custom:haos-"):\n        from haos.provider_moa_streams import create_once\n        return create_once(client, kwargs, stream=stream, task=task)\n'
    text = data.decode()
    if text.count(anchor) != 1:
        raise ValueError("pinned auxiliary dispatch changed")
    if not check_only:
        path.write_text(text.replace(anchor, addition + anchor))


def patch_a2a(upstream,expected_sha256,*,check_only=False):
    """Keep native callback construction/signing behind a scoped transport hook."""
    path=upstream/'plugins/platforms/a2a/adapter.py';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected_sha256:raise ValueError('A2A transport overlay belongs to another Hermes source')
    anchor='    def _send_push_notification(self, task_id: str, context_id: str, reply: str, state: str) -> None:\n'
    transport='            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310\n'
    addition='    def _open_push_notification(self, request, *, timeout):\n        """Scoped callback transport; native payload, signing and handling stay here."""\n        return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310\n\n'
    text=data.decode()
    if text.count(anchor)!=1 or text.count(transport)!=1:raise ValueError('pinned A2A callback transport changed')
    if not check_only:path.write_text(text.replace(anchor,addition+anchor).replace(transport,'            with self._open_push_notification(req, timeout=10) as resp:\n'))



def patch_buzz(upstream,expected_sha256,*,check_only=False):
    """Expose only the native subscription's scoped WebSocket constructor."""
    path=upstream/'plugins/platforms/buzz/adapter.py';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected_sha256:raise ValueError('Buzz transport overlay belongs to another Hermes source')
    anchor='    async def _websocket_loop(self) -> None:\n'
    transport='                async with websockets.connect(\n                    self._websocket_url(), open_timeout=_WS_AUTH_TIMEOUT, close_timeout=5,\n'
    addition='    def _open_websocket(self, **kwargs):\n        """Scoped socket transport; native authentication/subscription stay here."""\n        import websockets\n        return websockets.connect(self._websocket_url(), **kwargs)\n\n'
    text=data.decode()
    if text.count(anchor)!=1 or text.count(transport)!=1:raise ValueError('pinned Buzz subscription transport changed')
    if not check_only:path.write_text(text.replace(anchor,addition+anchor).replace(transport,'                async with self._open_websocket(\n                    open_timeout=_WS_AUTH_TIMEOUT, close_timeout=5,\n'))


def prepare(upstream: Path, overlay: Path, *, check_only=False):
    source = json.loads((overlay / "source.json").read_text())
    if (upstream / ".herald-os-upstream-sha").read_text().strip() != source["upstream_commit"]:
        raise ValueError("runtime overlay belongs to another Hermes commit")
    for filename, key in [("pyproject.toml", "pyproject_sha256"), ("uv.lock", "uv_lock_sha256")]:
        if hashlib.sha256((upstream / filename).read_bytes()).hexdigest() != source[key]:
            raise ValueError("upstream input changed: " + filename)
    requirements = (overlay / "requirements.txt").read_bytes()
    if hashlib.sha256(requirements).hexdigest() != source["requirements_sha256"]:
        raise ValueError("hashed runtime requirements changed without review")
    if source["python"] != "3.11" or source["extras"] != ["web", "messaging", "anthropic", "bedrock", "vertex", "azure-identity", "matrix", "voice", "feishu", "dingtalk"]:
        raise ValueError("runtime target changed")
    for name, version in {**source["security_versions"], **source.get("provider_versions", {}), **source.get("gateway_compatibility_versions", {})}.items():
        versions = re.findall(rf"^{re.escape(name)}==([^\s;]+)", requirements.decode(), re.M)
        if versions != [version]:
            raise ValueError("security version mismatch: " + name)
    path = upstream / "pyproject.toml"
    text = path.read_text()
    original = '"PyJWT[crypto]==2.13.0"'
    replacement = '"PyJWT[crypto]==' + source["security_versions"]["pyjwt"] + '"'
    if text.count(original) != 1:
        raise ValueError("upstream PyJWT constraint changed; review this overlay")
    patch_auxiliary(upstream, source["auxiliary_client_sha256"], check_only=True)
    patch_a2a(upstream,source['a2a_adapter_sha256'],check_only=True)
    patch_buzz(upstream,source['buzz_adapter_sha256'],check_only=True)
    if not check_only:
        patch_auxiliary(upstream,source['auxiliary_client_sha256'])
        patch_a2a(upstream,source['a2a_adapter_sha256'])
        patch_buzz(upstream,source['buzz_adapter_sha256'])
        path.write_text(text.replace(original, replacement))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    prepare(args.upstream, args.overlay, check_only=args.check)
