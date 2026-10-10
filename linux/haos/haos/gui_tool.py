"""Image-owned Hermes tool. The controller, not session text, grants GUI scope."""
import json
import socket
import time
import uuid
import os
import hashlib
import base64
from pathlib import Path

SOCKET = "/run/haos-gui-agent/gui.sock"


def request(method, params):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(SOCKET)
        data = json.dumps({"method": method, "params": params}, ensure_ascii=False).encode() + b"\n"
        if len(data) > 131072:
            raise ValueError("GUI request exceeds its limit")
        sock.sendall(data)
        response = bytearray()
        while b"\n" not in response:
            part = sock.recv(16384)
            if not part or len(response) + len(part) > 131072:
                raise ValueError("invalid GUI response")
            response.extend(part)
        reply = json.loads(response.split(b"\n", 1)[0])
        if not reply.get("ok"):
            raise PermissionError("GUI action denied or unavailable")
        return reply["result"]


def handler(args, **kwargs):
    key = None
    try:
        from gateway.session_context import get_session_env
        session = get_session_env("HERMES_UI_SESSION_ID") or get_session_env("HERMES_SESSION_ID")
        if not session:
            raise PermissionError("no Hermes session")
        if not isinstance(args, dict) or set(args) - {"id", "action"} or "action" not in args:
            raise ValueError("invalid tool parameters")
        key = args.get("id") or str(uuid.uuid4())
        result = request("gui.submit", {"session": session, "id": key, "action": args["action"]})
        deadline = time.monotonic() + 12
        while result["state"] in {"pending", "dispatched"} and time.monotonic() < deadline:
            time.sleep(0.15)
            result = request("gui.result", {"session": session, "id": key})
        data = result.get("result")
        if isinstance(data, dict) and "jpeg" in data:
            image = base64.b64decode(data.pop("jpeg"), validate=True)
            root = Path("/workspace/.haos-captures")
            root.mkdir(mode=0o700, exist_ok=True)
            if root.is_symlink():
                raise PermissionError("capture directory is not private")
            path = root / (str(uuid.uuid4()) + ".jpg")
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(image)
            data.update({"path": str(path), "sha256": hashlib.sha256(image).hexdigest()})
        return json.dumps(result)
    except Exception as exc:
        # Do not interpolate caller document/input or socket/provider credentials.
        return json.dumps({"id": key, "error": "GUI denied or unavailable; inspect this action ID before retrying", "reason": type(exc).__name__})


def register():
    from tools.registry import registry
    registry.register(name="haos_gui", toolset="terminal", handler=handler, check_fn=lambda: True,
                      description="Operate mission-owned native browser windows", schema={
        "name": "haos_gui",
        "description": "Operate a real isolated native local browser window in Herald. No network, scripts, files, clipboard, owner windows or system bridge access. Open accepts static local HTML (reports/forms); capture saves a real JPEG in /workspace/.haos-captures for vision tools, never the whole screen. Inspect reads actual form values (password/file fields redacted; truncation reported) to verify work. Use state for opaque window IDs; click coordinates refer to an 800x600 window (document begins at y=48), type plain text, key allows Tab/Enter/Backspace/Delete/arrows/Home/End/Escape. Every action belongs to the active mission and is audited. Reuse the returned action id with identical action to inspect uncertain responses; never blindly repeat side effects. A GUI receipt does not certify the mission goal.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Optional action UUID for safe retry; use returned id"},
            "action": {"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["open", "state", "focus", "close", "click", "type", "key", "capture", "inspect"]},
                "html": {"type": "string"}, "window": {"type": "string"}, "x": {"type": "integer"}, "y": {"type": "integer"},
                "text": {"type": "string"}, "key": {"type": "string"}}, "required": ["operation"]}}, "required": ["action"]}})
