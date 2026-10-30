"""Bounded, kernel-authenticated bridge to a separately isolated ACP identity.

The external CLI never runs in the broker holding other vendors' credentials.
Only this fixed provider is delegated; executable/arguments/paths are immutable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import socket
import stat
import struct
from types import SimpleNamespace

SOCKET = "/run/haos-provider-acp/control.sock"
COMMAND = "/usr/lib/haos/copilot/copilot"
HOME = "/var/lib/haos-provider-acp"
ARGS = ["--acp", "--stdio", "--available-tools=", "--deny-tool=shell", "--deny-tool=write",
        "--deny-tool=url", "--disable-builtin-mcps", "--disallow-temp-dir", "--log-level=none"]
MAX_INPUT, MAX_EVENT, MAX_OUTPUT = 4 * 1024 * 1024, 1024 * 1024, 32 * 1024 * 1024


def require_peer(peer, uid, *, allow_root=False):
    actual = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if type(uid) is not int or uid < 0 or (uid == 0 and not allow_root) or actual != uid:
        raise PermissionError("separate provider kernel identity required")


def frame(stream, limit):
    data = stream.readline(limit + 1)
    if not data.endswith(b"\n") or len(data) > limit:
        raise ValueError("ACP transport frame is incomplete or exceeds its bound")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("ACP transport frame must be an object")
    return value


def send(stream, value):
    data = json.dumps(value, ensure_ascii=False).encode() + b"\n"
    if len(data) > MAX_EVENT:
        raise ValueError("ACP response event exceeds its bound")
    stream.write(data)
    stream.flush()


class ACPClient:
    """SDK facade used only by the credential-holding model broker."""
    def __init__(self, policy):
        self.policy, self.peer = policy, None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def events(self, payload):
        peer = self.peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            peer.settimeout(190)
            info = Path(SOCKET).lstat()
            parent = Path(SOCKET).parent.lstat()
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o007
                    or parent.st_uid != 0 or parent.st_mode & 0o022):
                raise PermissionError("root-owned private ACP socket required")
            peer.connect(SOCKET)
            # SO_PEERCRED reflects systemd's credentials when it created the
            # listening socket, not the UID of the activated accepting worker.
            require_peer(peer, 0, allow_root=True)
            with peer.makefile("rwb") as stream:
                data = json.dumps({"policy": self.policy.data, "payload": payload}).encode() + b"\n"
                if len(data) > MAX_INPUT:
                    raise ValueError("ACP request exceeds its bound")
                stream.write(data)
                stream.flush()
                total = 0
                while True:
                    value = frame(stream, MAX_EVENT)
                    total += len(json.dumps(value).encode())
                    if total > MAX_OUTPUT:
                        raise ValueError("ACP response exceeds its bound")
                    if value.get("error"):
                        raise ConnectionError("isolated ACP session failed")
                    if value == {"done": True}:
                        return
                    if set(value) != {"event"} or not isinstance(value["event"], dict):
                        raise ValueError("invalid ACP event envelope")
                    yield value["event"]
        finally:
            peer.close()
            self.peer = None

    def create(self, **payload):
        payload.pop("timeout", None)
        result = self.events(payload)
        if payload.get("stream") is True:
            return result
        value = next(result)
        try:
            next(result)
        except StopIteration:
            return value
        raise ValueError("unexpected duplicate ACP completion")

    def close(self):
        if self.peer is not None:
            self.peer.close()


class TextFilter:
    """Hide the upstream XML tool bridge and credentials across chunk boundaries."""
    def __init__(self, redactor, emit):
        self.redactor, self.emit = redactor, emit
        self.pending, self.in_tool, self.json_only, self.started = "", False, False, False

    def feed(self, text, final=False):
        self.pending += text
        if final and self.in_tool and not self.pending:
            raise ValueError("incomplete ACP tool call")
        if len(self.pending.encode()) > MAX_INPUT:
            raise ValueError("ACP tool bridge exceeds its bound")
        if not self.started and self.pending.strip():
            self.started = True
            self.json_only = self.pending.lstrip().startswith("{")
        if self.json_only:
            return
        while self.pending:
            marker = "</tool_call>" if self.in_tool else "<tool_call>"
            index = self.pending.find(marker)
            if index >= 0:
                if not self.in_tool:
                    self._text(self.pending[:index])
                self.pending = self.pending[index + len(marker):]
                self.in_tool = not self.in_tool
                continue
            if self.in_tool:
                if final:
                    raise ValueError("incomplete ACP tool call")
                return
            keep = 0
            if not final:
                for token in [marker, *self.redactor.secrets]:
                    for length in range(1, min(len(token), len(self.pending) + 1)):
                        if self.pending.endswith(token[:length]):
                            keep = max(keep, length)
            cut = len(self.pending) - keep
            # Never split a complete credential at the retention boundary.
            for token in self.redactor.secrets:
                begin = self.pending.find(token)
                while begin >= 0:
                    if begin < cut < begin + len(token):
                        cut = begin
                    begin = self.pending.find(token, begin + 1)
            if cut:
                self._text(self.pending[:cut])
                self.pending = self.pending[cut:]
            return

    def _text(self, value):
        if value:
            self.emit(self.redactor.text(value))


def private_secrets(base):
    """CLI's private token file may be reflected; never transmit its contents."""
    found = []
    def collect(value, sensitive=False):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, sensitive or any(s in key.lower() for s in ("token", "secret", "password")))
        elif isinstance(value, list):
            for item in value:
                collect(item, sensitive)
        elif sensitive and isinstance(value, str) and value:
            found.append(value)
    directory = Path(base) / ".copilot"
    if directory.is_dir():
        for path in directory.glob("*.json"):
            if path.is_file() and path.stat().st_size <= MAX_EVENT:
                try:
                    collect(json.loads(path.read_text()))
                except (OSError, ValueError):
                    pass
    return found


def isolated_client(*, command=COMMAND, args=None, cwd=None):
    """Reuse pinned Hermes ACP framing/tool codec, overriding unsafe defaults."""
    from agent.copilot_acp_client import CopilotACPClient, _model_selection_request
    class Isolated(CopilotACPClient):
        sink = None
        size = 0

        def _handle_server_message(self, msg, **kwargs):
            value = (msg.get("params") or {}).get("update") or {}
            content = value.get("content") or {}
            if value.get("sessionUpdate") == "agent_message_chunk" and isinstance(content, dict):
                text = content.get("text") or ""
                if not isinstance(text, str):
                    raise ValueError("invalid ACP text delta")
                self.size += len(text.encode())
                if self.size > MAX_OUTPUT:
                    raise ValueError("ACP output exceeds its bound")
                if self.sink:
                    self.sink(text)
            kwargs["allow_file_requests"] = False
            return super()._handle_server_message(msg, **kwargs)

        def _run_prompt(self, prompt_text, *, timeout_seconds, model=None):
            with self._session(min(timeout_seconds, 180), allow_file_requests=False) as (session, request):
                selection = _model_selection_request(session, model or "")
                # Upstream silently falls back; an owner-approved model must
                # actually be selected, never substituted by a CLI default.
                if not selection:
                    raise PermissionError("ACP account does not offer the approved model")
                request(*selection)
                parts, reasoning = [], []
                result = request("session/prompt", {"sessionId": session["sessionId"],
                    "prompt": [{"type": "text", "text": prompt_text}]}, text_parts=parts, reasoning_parts=reasoning)
                if not isinstance(result, dict) or result.get("stopReason") not in {"end_turn", "max_tokens"}:
                    raise ConnectionError("ACP session has no successful terminal receipt")
                self.stop_reason = result["stopReason"]
                return "".join(parts), "".join(reasoning)
    return Isolated(acp_command=command, acp_args=ARGS if args is None else args, acp_cwd=cwd or HOME)


def completion_events(payload, client, redactor, emit):
    from .provider_native import plain
    stream = payload.get("stream") is True
    def chunk(delta, finish=None):
        emit({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
              "model": payload["model"], "object": "chat.completion.chunk"})
    filtered = TextFilter(redactor, lambda text: chunk({"content": text}))
    if stream:
        client.sink = filtered.feed
    # The actual upstream codec formats messages/tools and parses tool calls.
    value = plain(client.chat.completions.create(**{**payload, "stream": False, "timeout": 180}))
    value.pop("usage", None)
    if getattr(client, "stop_reason", None) == "max_tokens":
        value["choices"][0]["finish_reason"] = "length"
    if not stream:
        emit(redactor.clean(value))
        return
    filtered.feed("", final=True)
    message = value["choices"][0]["message"]
    if filtered.json_only:
        text = message.get("content")
        if text:
            chunk({"content": redactor.text(text)})
    calls = message.get("tool_calls")
    if calls:
        chunk({"tool_calls": [{"index": index, **redactor.clean(call)} for index, call in enumerate(calls)]})
    chunk({}, value["choices"][0]["finish_reason"])
    # Upstream ACP does not report token usage; do not fabricate zero counts.


def handle(peer, uid, *, config=Path("/etc/haos/provider.json"), factory=isolated_client):
    from .provider_policy import ProviderPolicy
    from .provider_routes import ProviderRoutes
    from .sandbox import trusted_json
    from .redaction import Redactor
    require_peer(peer, uid)
    peer.settimeout(190)
    with peer.makefile("rwb") as stream:
        value = frame(stream, MAX_INPUT)
        if set(value) != {"policy", "payload"}:
            raise PermissionError("only a fixed ACP inference request is authorized")
        policy = ProviderPolicy(value["policy"])
        current = ProviderRoutes(trusted_json(config))
        if policy.provider != "copilot-acp" or not any(p.data == policy.data for p in current.routes.values()):
            raise PermissionError("ACP route was withdrawn or changed")
        payload = policy.request("/v1/chat/completions", value["payload"])
        client = factory()
        try:
            redactor = Redactor(private_secrets(HOME))
            # A dedicated empty working directory prevents workspace/skill
            # discovery. The CLI's authentication HOME remains separate.
            completion_events(payload, client, redactor, lambda event: send(stream, {"event": event}))
            send(stream, {"done": True})
        finally:
            client.close()


def main():
    import threading
    account = pwd.getpwnam("haos-provider-acp")
    if os.geteuid() != account.pw_uid or account.pw_uid == 0 or os.environ.get("HOME") != HOME:
        raise PermissionError("separate ACP service identity required")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise PermissionError("root-owned ACP socket activation required")
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX or listener.getsockname() != SOCKET:
        raise PermissionError("unexpected ACP listener")
    uid = pwd.getpwnam("haos-provider").pw_uid
    slots = threading.BoundedSemaphore(2)
    work = Path(HOME) / "sessions"
    work.mkdir(mode=0o700, exist_ok=True)
    def run(peer):
        import tempfile
        try:
            with peer, tempfile.TemporaryDirectory(dir=work) as cwd:
                handle(peer, uid, factory=lambda: isolated_client(cwd=cwd))
        except Exception:
            # Never print the CLI's token-bearing stderr or exception detail.
            try:
                peer.sendall(b'{"error":true}\n')
            except OSError:
                pass
        finally:
            slots.release()
    while True:
        peer, _ = listener.accept()
        if not slots.acquire(blocking=False):
            peer.close()
            continue
        threading.Thread(target=run, args=(peer,), daemon=True).start()


if __name__ == "__main__":
    main()
