"""Tool schemas and handlers for the ``hermes_os`` toolset.

Every handler follows the same shape: validate arguments, decide the permission tier for the
requested action, ``authorize`` (protected paths first, then the tier policy / approval gate),
execute through the host adapter, and ``audit.record`` the outcome. Handlers return JSON strings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from . import audit
from .host import HostNotSupported, host
from .host.base import FileSearch
from .permissions import Tier, authorize
from .util import expand, fail, ok, run, truncate

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


def _enum(*values: str, description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "enum": list(values)}
    if description:
        schema["description"] = description
    return schema


def _desc(kind: dict[str, Any], description: str) -> dict[str, Any]:
    return {**kind, "description": description}


def _schema(name: str, description: str, properties: dict[str, Any], required: Iterable[str] = ()) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": list(required)}}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict[str, Any]
    handler: Callable[..., str]
    emoji: str


def bridge_enabled() -> bool:
    """``hermes_os.bridge.enabled`` in config.yaml (default on). HERMES_OS=1 (set by the shell) also enables."""
    if os.environ.get("HERMES_OS_BRIDGE_DISABLED") == "1":
        return False
    try:
        from hermes_cli.config import load_config

        section = (load_config() or {}).get("hermes_os") or {}
        bridge = section.get("bridge") if isinstance(section, dict) else None
        if isinstance(bridge, dict) and bridge.get("enabled") is False:
            return False
    except Exception:  # noqa: BLE001 - config unreadable: keep the default.
        pass
    return True


def _int(args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(args.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _finish(*, tool: str, tier: Tier, action: str | None, args: dict[str, Any], decision: str, ok_: bool, summary: str | None = None, error: str | None = None) -> None:
    audit.record(tool=tool, tier=tier.value, action=action, args=args, decision=decision, ok=ok_, summary=summary, error=error)


def _guarded(tool: str, tier: Tier, action: str, summary: str, args: dict[str, Any], paths: Iterable[Path], execute: Callable[[], dict[str, Any]]) -> str:
    """Authorize, run, audit. Shared by every act/mutate/destructive handler."""
    decision = authorize(tool, tier, action, summary, paths=paths)
    if not decision.allowed:
        _finish(tool=tool, tier=tier, action=action, args=args, decision=decision.outcome, ok_=False, summary=summary, error=decision.message)
        return fail(decision.message or "not permitted", decision=decision.outcome, summary=summary)
    try:
        payload = execute()
    except HostNotSupported as exc:
        _finish(tool=tool, tier=tier, action=action, args=args, decision=decision.outcome, ok_=False, summary=summary, error=str(exc))
        return fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - every host error becomes a tool result, never a crash.
        _finish(tool=tool, tier=tier, action=action, args=args, decision=decision.outcome, ok_=False, summary=summary, error=str(exc))
        return fail(str(exc), summary=summary)
    _finish(tool=tool, tier=tier, action=action, args=args, decision=decision.outcome, ok_=True, summary=summary)
    return ok(summary=summary, **payload)


def _read(tool: str, action: str | None, args: dict[str, Any], execute: Callable[[], dict[str, Any]]) -> str:
    return _guarded(tool, Tier.READ, action or "read", f"{tool} {action or ''}".strip(), args, (), execute)


# ---------------------------------------------------------------------------------------------
# system_info
# ---------------------------------------------------------------------------------------------

SYSTEM_INFO_SCHEMA = _schema(
    "system_info",
    "Read this computer's system facts: OS version, chip, cores, memory (total/used), load average, uptime, disks (total/used/free per volume) and battery. Use it to answer questions about the machine, before recommending cleanups, or to ground disk/memory advice in numbers.",
    {},
)


def handle_system_info(args: dict[str, Any], **_: Any) -> str:
    return _read("system_info", None, args, lambda: host().system_info())


# ---------------------------------------------------------------------------------------------
# system_processes
# ---------------------------------------------------------------------------------------------

SYSTEM_PROCESSES_SCHEMA = _schema(
    "system_processes",
    "Inspect running processes. action=top lists the heaviest processes by CPU or memory ('what is using the most CPU?'); action=find matches processes by name; action=port shows what is listening on a TCP/UDP port ('what's on port 3000?'). Read-only; use system_kill_process to stop something.",
    {
        "action": _enum("top", "find", "port", description="What to look up."),
        "sort": _enum("cpu", "memory", description="For action=top: ranking key (default cpu)."),
        "name": _desc(_STR, "For action=find: substring matched case-insensitively against the command path."),
        "port": _desc(_INT, "For action=port: the port number."),
        "limit": _desc(_INT, "Maximum rows (default 15, max 100)."),
    },
    required=("action",),
)


def handle_system_processes(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "top")
    limit = _int(args, "limit", 15, 1, 100)

    def execute() -> dict[str, Any]:
        adapter = host()
        if action == "top":
            sort = "memory" if str(args.get("sort") or "cpu") == "memory" else "cpu"
            return {"sort": sort, "processes": [row.to_dict() for row in adapter.list_processes(sort, limit)]}
        if action == "find":
            name = str(args.get("name") or "").strip()
            if not name:
                raise ValueError("name is required for action=find")
            return {"name": name, "processes": [row.to_dict() for row in adapter.find_processes(name, limit)]}
        if action == "port":
            port = _int(args, "port", 0, 1, 65535)
            if not args.get("port"):
                raise ValueError("port is required for action=port")
            listeners = adapter.listeners_on_port(port)
            return {"port": port, "listeners": [row.to_dict() for row in listeners], "note": None if listeners else f"Nothing is listening on port {port}."}
        raise ValueError(f"unknown action '{action}'")

    return _read("system_processes", action, args, execute)


# ---------------------------------------------------------------------------------------------
# system_disk_usage
# ---------------------------------------------------------------------------------------------

SYSTEM_DISK_USAGE_SCHEMA = _schema(
    "system_disk_usage",
    "Find what takes up disk space: the largest entries directly under a directory (default: the user's home), biggest first. Start broad, then call again on the biggest child to drill in. Slow on huge trees; bounded by a timeout. Read-only.",
    {
        "path": _desc(_STR, "Directory to measure (default ~). Supports ~ expansion."),
        "depth": _desc(_INT, "How many levels to report below path (default 1, max 3)."),
        "limit": _desc(_INT, "Maximum entries to return (default 20, max 100)."),
    },
)


def handle_system_disk_usage(args: dict[str, Any], **_: Any) -> str:
    target = expand(str(args.get("path") or "~"))
    depth = _int(args, "depth", 1, 1, 3)
    limit = _int(args, "limit", 20, 1, 100)

    def execute() -> dict[str, Any]:
        if not target.is_dir():
            raise ValueError(f"{target} is not a directory")
        return host().disk_usage(target, depth, limit, timeout=90.0)

    return _guarded("system_disk_usage", Tier.READ, "measure", f"measure disk usage under {target}", args, (target,), execute)


# ---------------------------------------------------------------------------------------------
# system_find_files
# ---------------------------------------------------------------------------------------------

SYSTEM_FIND_FILES_SCHEMA = _schema(
    "system_find_files",
    "Search this Mac with Spotlight. Combine: text (content or display name), name (filename substring), kind (image, screenshot, document, pdf, video, audio, folder, code, archive), when (today, yesterday, this_week, last_7_days, this_month) or explicit since/until dates, scope (a directory), extensions. Example: 'screenshots I took yesterday' -> kind=screenshot, when=yesterday. Returns paths newest first. Read-only.",
    {
        "text": _desc(_STR, "Words to match in file content or display name."),
        "name": _desc(_STR, "Filename substring (case-insensitive)."),
        "kind": _enum("any", "image", "screenshot", "document", "pdf", "video", "audio", "folder", "code", "archive"),
        "when": _enum("today", "yesterday", "this_week", "last_7_days", "this_month", description="Relative creation-date window."),
        "since": _desc(_STR, "Created on/after this date (YYYY-MM-DD or ISO 8601)."),
        "until": _desc(_STR, "Created before the end of this date (YYYY-MM-DD or ISO 8601)."),
        "scope": _desc(_STR, "Only search under this directory (e.g. ~/Desktop)."),
        "extensions": {"type": "array", "items": _STR, "description": "File extensions to match, e.g. [\"png\", \"jpg\"]."},
        "limit": _desc(_INT, "Maximum results (default 50, max 200)."),
    },
)


def resolve_when(when: str | None, today: date | None = None) -> tuple[str | None, str | None]:
    """Translate a relative window into inclusive ``since`` / exclusive-end ``until`` dates (pure; tested)."""
    if not when:
        return None, None
    today = today or date.today()
    if when == "today":
        return today.isoformat(), today.isoformat()
    if when == "yesterday":
        y = today - timedelta(days=1)
        return y.isoformat(), y.isoformat()
    if when == "this_week":
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    if when == "last_7_days":
        return (today - timedelta(days=7)).isoformat(), today.isoformat()
    if when == "this_month":
        return today.replace(day=1).isoformat(), today.isoformat()
    raise ValueError(f"unknown when '{when}'")


def handle_system_find_files(args: dict[str, Any], **_: Any) -> str:
    def execute() -> dict[str, Any]:
        since, until = args.get("since"), args.get("until")
        if args.get("when"):
            since, until = resolve_when(str(args["when"]))
        exts = args.get("extensions") or ()
        search = FileSearch(
            text=(args.get("text") or None), name=(args.get("name") or None), kind=str(args.get("kind") or "any"),
            since=since, until=until, scope=(args.get("scope") or None),
            extensions=tuple(str(e) for e in exts) if isinstance(exts, list) else (), limit=_int(args, "limit", 50, 1, 200),
        )
        results = host().find_files(search)
        return {"count": len(results), "files": [f.to_dict() for f in results], "note": None if results else "No matches. Spotlight only indexes locations the user allows; try a broader query or a different kind."}

    return _read("system_find_files", "search", args, execute)


# ---------------------------------------------------------------------------------------------
# system_apps
# ---------------------------------------------------------------------------------------------

SYSTEM_APPS_SCHEMA = _schema(
    "system_apps",
    "Applications on this Mac. action=installed lists installed apps (optionally filtered by name); action=running lists apps currently open; action=quit asks an app to quit (force=true kills it). Use system_open to launch an app.",
    {
        "action": _enum("installed", "running", "quit"),
        "filter": _desc(_STR, "For installed/running: case-insensitive name substring."),
        "name": _desc(_STR, "For quit: the application name."),
        "force": _desc(_BOOL, "For quit: force-terminate instead of asking politely (loses unsaved work)."),
    },
    required=("action",),
)


def handle_system_apps(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "installed")
    needle = str(args.get("filter") or "").strip().lower()
    if action == "quit":
        name = str(args.get("name") or "").strip()
        if not name:
            return fail("name is required for action=quit")
        force = bool(args.get("force"))
        summary = f"{'force quit' if force else 'quit'} {name}"
        return _guarded("system_apps", Tier.DESTRUCTIVE, "quit", summary, args, (), lambda: (host().quit_app(name, force), {"app": name, "forced": force})[1])

    def execute() -> dict[str, Any]:
        adapter = host()
        apps = adapter.installed_apps() if action == "installed" else adapter.running_apps() if action == "running" else None
        if apps is None:
            raise ValueError(f"unknown action '{action}'")
        if needle:
            apps = [a for a in apps if needle in a.name.lower()]
        return {"count": len(apps), "apps": [a.to_dict() for a in apps[:300]]}

    return _read("system_apps", action, args, execute)


# ---------------------------------------------------------------------------------------------
# system_open
# ---------------------------------------------------------------------------------------------

EDITOR_APPS = {"vscode": "Visual Studio Code", "code": "Visual Studio Code", "cursor": "Cursor", "xcode": "Xcode", "zed": "Zed", "finder": None, "terminal": "Terminal", "iterm": "iTerm"}

SYSTEM_OPEN_SCHEMA = _schema(
    "system_open",
    "Open things for the user. target=app launches an application by name ('Open Safari'); target=url opens a URL (optionally in a specific browser); target=path opens a file or folder with its default app or a named app; target=reveal shows a file in Finder; target=editor opens a folder/file in a code editor (editor=vscode|cursor|xcode|zed|terminal), e.g. 'open this repo in VS Code'; target=settings opens a System Settings pane (pane=privacy_and_security, wifi, bluetooth, sound, displays, notifications, screen_recording, accessibility_privacy, automation, ...). Runs immediately; every call is audited.",
    {
        "target": _enum("app", "url", "path", "reveal", "editor", "settings"),
        "app": _desc(_STR, "Application name (for target=app, or the app to open a url/path with)."),
        "url": _desc(_STR, "For target=url."),
        "path": _desc(_STR, "For target=path / reveal / editor. Supports ~."),
        "editor": _enum("vscode", "cursor", "xcode", "zed", "terminal", "iterm", description="For target=editor (default vscode)."),
        "pane": _desc(_STR, "For target=settings: the System Settings pane name."),
        "args": {"type": "array", "items": _STR, "description": "For target=app: extra launch arguments."},
    },
    required=("target",),
)


def handle_system_open(args: dict[str, Any], **_: Any) -> str:
    target = str(args.get("target") or "")
    adapter = host()
    if target == "app":
        name = str(args.get("app") or "").strip()
        if not name:
            return fail("app is required for target=app")
        extra = [str(a) for a in (args.get("args") or [])]
        return _guarded("system_open", Tier.ACT, "app", f"open {name}", args, (), lambda: (adapter.open_app(name, extra), {"opened": name})[1])
    if target == "settings":
        pane = str(args.get("pane") or "general")
        return _guarded("system_open", Tier.ACT, "settings", f"open System Settings > {pane}", args, (), lambda: {"pane": pane, "opened": adapter.open_settings(pane)})
    if target == "url":
        url = str(args.get("url") or "").strip()
        if url.lower().startswith("x-apple.systempreferences:"):
            return _guarded("system_open", Tier.ACT, "settings", f"open System Settings ({url})", args, (), lambda: (adapter.open_url(url), {"opened": url})[1])
        if not url.lower().startswith(("http://", "https://", "mailto:", "file://")):
            return fail("url must start with http://, https://, mailto: or file://")
        app = args.get("app") or None
        return _guarded("system_open", Tier.ACT, "url", f"open {url}" + (f" in {app}" if app else ""), args, (), lambda: (adapter.open_url(url, app), {"opened": url, "app": app})[1])
    if target in ("path", "reveal", "editor"):
        raw = str(args.get("path") or "").strip()
        if not raw:
            return fail("path is required")
        path = expand(raw)
        if not path.exists():
            return fail(f"{path} does not exist")
        if target == "reveal":
            return _guarded("system_open", Tier.ACT, "reveal", f"reveal {path} in Finder", args, (path,), lambda: (adapter.reveal(path), {"revealed": str(path)})[1])
        if target == "editor":
            editor = str(args.get("editor") or "vscode").lower()
            app = EDITOR_APPS.get(editor, editor)
            if app is None:
                return _guarded("system_open", Tier.ACT, "reveal", f"reveal {path} in Finder", args, (path,), lambda: (adapter.reveal(path), {"revealed": str(path)})[1])
            return _guarded("system_open", Tier.ACT, "editor", f"open {path} in {app}", args, (path,), lambda: (adapter.open_path(path, app), {"opened": str(path), "app": app})[1])
        app = args.get("app") or None
        return _guarded("system_open", Tier.ACT, "path", f"open {path}" + (f" with {app}" if app else ""), args, (path,), lambda: (adapter.open_path(path, app), {"opened": str(path), "app": app})[1])
    return fail(f"unknown target '{target}'")


# ---------------------------------------------------------------------------------------------
# system_kill_process
# ---------------------------------------------------------------------------------------------

SYSTEM_KILL_PROCESS_SCHEMA = _schema(
    "system_kill_process",
    "Stop a process. Identify it by pid, by the port it listens on ('kill the process on port 3000'), or by name (must match exactly one process unless all=true). Sends SIGTERM; force=true sends SIGKILL. Destructive: the user is always asked to confirm.",
    {
        "pid": _desc(_INT, "Process id."),
        "port": _desc(_INT, "Stop whatever is listening on this port."),
        "name": _desc(_STR, "Process name / command substring."),
        "all": _desc(_BOOL, "For name: stop every match instead of requiring exactly one."),
        "force": _desc(_BOOL, "SIGKILL instead of SIGTERM."),
    },
)


def handle_system_kill_process(args: dict[str, Any], **_: Any) -> str:
    adapter = host()
    force = bool(args.get("force"))
    targets: list[dict[str, Any]] = []
    try:
        if args.get("pid"):
            pid = int(args["pid"])
            match = adapter.find_processes("", 5000)
            row = next((r for r in match if r.pid == pid), None)
            targets = [{"pid": pid, "name": row.name if row else "unknown", "command": row.command if row else ""}]
        elif args.get("port"):
            port = int(args["port"])
            listeners = adapter.listeners_on_port(port)
            if not listeners:
                return fail(f"Nothing is listening on port {port}.")
            targets = [{"pid": l.pid, "name": l.command, "command": l.command, "port": port} for l in listeners]
        elif args.get("name"):
            name = str(args["name"]).strip()
            rows = [r for r in adapter.find_processes(name, 200) if r.pid != os.getpid()]
            if not rows:
                return fail(f"No process matches '{name}'.")
            if len(rows) > 1 and not args.get("all"):
                return fail(f"'{name}' matches {len(rows)} processes; pass pid or all=true.", candidates=[r.to_dict() for r in rows[:20]])
            targets = [{"pid": r.pid, "name": r.name, "command": r.command} for r in rows]
        else:
            return fail("provide pid, port or name")
    except (TypeError, ValueError) as exc:
        return fail(str(exc))

    if any(t["pid"] in (0, 1, os.getpid(), os.getppid()) for t in targets):
        return fail("Refusing to stop a system-critical process or Hermes itself.")
    label = ", ".join(f"{t['name']} (pid {t['pid']})" for t in targets)
    summary = f"{'force kill' if force else 'terminate'} {label}"

    def execute() -> dict[str, Any]:
        stopped, errors = [], []
        for t in targets:
            try:
                adapter.kill(int(t["pid"]), force)
                stopped.append(t)
            except ProcessLookupError:
                errors.append({**t, "error": "already exited"})
            except PermissionError:
                errors.append({**t, "error": "permission denied (owned by another user)"})
        return {"stopped": stopped, "errors": errors, "signal": "SIGKILL" if force else "SIGTERM"}

    return _guarded("system_kill_process", Tier.DESTRUCTIVE, "kill", summary, args, (), execute)


# ---------------------------------------------------------------------------------------------
# system_files
# ---------------------------------------------------------------------------------------------

SYSTEM_FILES_SCHEMA = _schema(
    "system_files",
    "Organise files and folders on this Mac. action=mkdir creates a folder (path); action=move moves/renames one item (path -> to); action=copy copies a file or folder (path -> to); action=trash moves items to the Trash (paths; never permanent deletion); action=batch applies a list of operations [{op: mkdir|move|copy|trash, path, to}] in one confirmation, ideal for 'organise these files'. Set dry_run=true first to show the plan; the user confirms mutating actions once per batch. Use the write_file tool to create file contents.",
    {
        "action": _enum("mkdir", "move", "copy", "trash", "batch"),
        "path": _desc(_STR, "Target path for mkdir/move/copy/trash."),
        "to": _desc(_STR, "Destination for move/copy (a folder, or the new full path)."),
        "paths": {"type": "array", "items": _STR, "description": "For trash: several items."},
        "operations": {
            "type": "array",
            "description": "For batch: ordered operations.",
            "items": {"type": "object", "properties": {"op": _enum("mkdir", "move", "copy", "trash"), "path": _STR, "to": _STR}, "required": ["op", "path"]},
        },
        "dry_run": _desc(_BOOL, "Only describe what would happen."),
    },
    required=("action",),
)


@dataclass
class FileOp:
    op: str
    path: Path
    to: Path | None = None

    def describe(self) -> str:
        if self.op == "mkdir":
            return f"create folder {self.path}"
        if self.op == "move":
            return f"move {self.path} -> {self.to}"
        if self.op == "copy":
            return f"copy {self.path} -> {self.to}"
        return f"trash {self.path}"

    def touched(self) -> list[Path]:
        return [p for p in (self.path, self.to) if p is not None]


def plan_operations(args: dict[str, Any]) -> list[FileOp]:
    """Normalise the tool arguments into an ordered operation list (pure; tested)."""
    action = str(args.get("action") or "")
    ops: list[FileOp] = []
    if action == "batch":
        for raw in args.get("operations") or []:
            if not isinstance(raw, dict):
                continue
            op = str(raw.get("op") or "")
            if op not in ("mkdir", "move", "copy", "trash") or not raw.get("path"):
                raise ValueError(f"invalid operation {raw}")
            ops.append(FileOp(op, expand(str(raw["path"])), expand(str(raw["to"])) if raw.get("to") else None))
    elif action == "mkdir":
        if not args.get("path"):
            raise ValueError("path is required")
        ops.append(FileOp("mkdir", expand(str(args["path"]))))
    elif action in ("move", "copy"):
        if not args.get("path") or not args.get("to"):
            raise ValueError(f"path and to are required for {action}")
        ops.append(FileOp(action, expand(str(args["path"])), expand(str(args["to"]))))
    elif action == "trash":
        raw_paths = list(args.get("paths") or ([] if not args.get("path") else [args["path"]]))
        if not raw_paths:
            raise ValueError("paths (or path) is required for trash")
        ops.extend(FileOp("trash", expand(str(p))) for p in raw_paths)
    else:
        raise ValueError(f"unknown action '{action}'")
    for op in ops:
        if op.op in ("move", "copy") and op.to is None:
            raise ValueError(f"{op.op} of {op.path} needs 'to'")
    return ops


def _resolve_move_target(source: Path, to: Path) -> Path:
    return to / source.name if to.is_dir() else to


def handle_system_files(args: dict[str, Any], **_: Any) -> str:
    try:
        ops = plan_operations(args)
    except ValueError as exc:
        return fail(str(exc))
    if not ops:
        return fail("nothing to do")
    tier = Tier.DESTRUCTIVE if any(op.op == "trash" for op in ops) else Tier.MUTATE
    plan = [op.describe() for op in ops]
    problems: list[str] = []
    for op in ops:
        if op.op in ("move", "copy", "trash") and not op.path.exists():
            problems.append(f"{op.path} does not exist")
        if op.op == "mkdir" and op.path.exists() and not op.path.is_dir():
            problems.append(f"{op.path} exists and is not a folder")
    if args.get("dry_run"):
        audit.record(tool="system_files", tier=tier.value, action="plan", args=args, decision="dry_run", ok=not problems, summary=f"{len(ops)} operation(s) planned")
        return ok(dry_run=True, tier=tier.value, plan=plan, problems=problems, note="Call again with dry_run=false to apply; the user will be asked to confirm.")
    if problems:
        return fail("; ".join(problems), plan=plan)
    summary = plan[0] if len(plan) == 1 else f"{len(plan)} file operations: " + "; ".join(truncate(p, 80) for p in plan[:4]) + (" …" if len(plan) > 4 else "")

    def execute() -> dict[str, Any]:
        adapter = host()
        done: list[str] = []
        for op in ops:
            if op.op == "mkdir":
                op.path.mkdir(parents=True, exist_ok=True)
            elif op.op == "move":
                target = _resolve_move_target(op.path, op.to)  # type: ignore[arg-type]
                if target.exists():
                    raise FileExistsError(f"{target} already exists; not overwriting")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(op.path), str(target))
            elif op.op == "copy":
                target = _resolve_move_target(op.path, op.to)  # type: ignore[arg-type]
                if target.exists():
                    raise FileExistsError(f"{target} already exists; not overwriting")
                target.parent.mkdir(parents=True, exist_ok=True)
                if op.path.is_dir():
                    shutil.copytree(str(op.path), str(target))
                else:
                    shutil.copy2(str(op.path), str(target))
            elif op.op == "trash":
                adapter.trash([op.path])
            done.append(op.describe())
        return {"applied": done}

    touched = [p for op in ops for p in op.touched()]
    return _guarded("system_files", tier, "batch" if len(ops) > 1 else ops[0].op, summary, args, touched, execute)


# ---------------------------------------------------------------------------------------------
# system_network
# ---------------------------------------------------------------------------------------------

SYSTEM_NETWORK_SCHEMA = _schema(
    "system_network",
    "Connectivity on this Mac. action=status: online/offline, default interface, gateway, DNS, each active interface with its IPv4, and the Wi-Fi link (connected, channel, rate, signal; macOS hides the network name unless Location Services is granted). action=bluetooth: power state, connected and paired devices. Read-only.",
    {"action": _enum("status", "bluetooth", description="Default status.")},
)


def handle_system_network(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status")

    def execute() -> dict[str, Any]:
        if action == "bluetooth":
            return {"bluetooth": host().bluetooth_status()}
        return host().network_status()

    return _read("system_network", action, args, execute)


# ---------------------------------------------------------------------------------------------
# system_control
# ---------------------------------------------------------------------------------------------

SYSTEM_CONTROL_SCHEMA = _schema(
    "system_control",
    "Read or change device settings. Reads: audio (output/input/alert volume, mute), appearance (dark mode, displays). Actions: set_volume (percent and/or muted), set_dark_mode (enabled), notify (title, body: a macOS notification), open_settings (pane, e.g. privacy_and_security, screen_recording, wifi, bluetooth, sound, displays, notifications), sleep_display, lock_screen, set_wifi (enabled). Actions run immediately and are audited; set_wifi asks first.",
    {
        "action": _enum("audio", "appearance", "set_volume", "set_dark_mode", "notify", "open_settings", "sleep_display", "lock_screen", "set_wifi"),
        "percent": _desc(_INT, "For set_volume: 0-100."),
        "muted": _desc(_BOOL, "For set_volume."),
        "enabled": _desc(_BOOL, "For set_dark_mode / set_wifi."),
        "title": _desc(_STR, "For notify."),
        "body": _desc(_STR, "For notify."),
        "pane": _desc(_STR, "For open_settings: a System Settings pane name."),
    },
    required=("action",),
)


def handle_system_control(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "")
    adapter = host()
    if action == "audio":
        return _read("system_control", action, args, lambda: {"audio": adapter.audio_status()})
    if action == "appearance":
        return _read("system_control", action, args, lambda: adapter.appearance_status())
    if action == "set_volume":
        percent = args.get("percent")
        muted = args.get("muted")
        if percent is None and muted is None:
            return fail("set_volume needs percent and/or muted")
        parts = [f"volume {int(percent)}%" if percent is not None else "", ("mute" if muted else "unmute") if muted is not None else ""]
        summary = "set " + " and ".join(p for p in parts if p)
        return _guarded("system_control", Tier.ACT, action, summary, args, (), lambda: {"audio": adapter.set_volume(int(percent) if percent is not None else None, bool(muted) if muted is not None else None)})
    if action == "set_dark_mode":
        enabled = bool(args.get("enabled", True))
        return _guarded("system_control", Tier.ACT, action, f"turn dark mode {'on' if enabled else 'off'}", args, (), lambda: (adapter.set_dark_mode(enabled), {"dark_mode": enabled})[1])
    if action == "notify":
        title = str(args.get("title") or "Hermes")
        body = str(args.get("body") or "")
        if not body:
            return fail("notify needs body")
        return _guarded("system_control", Tier.ACT, action, f"notify: {title}", args, (), lambda: (adapter.notify(title, body), {"notified": True})[1])
    if action == "open_settings":
        pane = str(args.get("pane") or "general")
        return _guarded("system_control", Tier.ACT, action, f"open System Settings > {pane}", args, (), lambda: {"opened": adapter.open_settings(pane)})
    if action == "sleep_display":
        return _guarded("system_control", Tier.ACT, action, "put the display to sleep", args, (), lambda: (adapter.sleep_display(), {"display": "sleeping"})[1])
    if action == "lock_screen":
        return _guarded("system_control", Tier.ACT, action, "lock the screen", args, (), lambda: (adapter.lock_screen(), {"locked": True})[1])
    if action == "set_wifi":
        enabled = bool(args.get("enabled", True))
        return _guarded("system_control", Tier.MUTATE, action, f"turn Wi-Fi {'on' if enabled else 'off'}", args, (), lambda: (adapter.set_wifi_power(enabled), {"wifi": enabled})[1])
    return fail(f"unknown action '{action}'")


# ---------------------------------------------------------------------------------------------
# system_logs
# ---------------------------------------------------------------------------------------------

SYSTEM_LOGS_SCHEMA = _schema(
    "system_logs",
    "Read the unified system log (diagnostics). minutes (default 10, max 240), level error|fault|any (default error), optional process name filter, limit (default 40, max 200). Returns the most recent matching lines, compact style. Read-only; can take several seconds.",
    {
        "minutes": _INT,
        "level": _enum("error", "fault", "any"),
        "process": _desc(_STR, "Only lines from this process (e.g. WindowServer, kernel)."),
        "limit": _INT,
    },
)


def handle_system_logs(args: dict[str, Any], **_: Any) -> str:
    minutes = _int(args, "minutes", 10, 1, 240)
    limit = _int(args, "limit", 40, 1, 200)
    level = str(args.get("level") or "error")
    process = (args.get("process") or None) and str(args["process"])
    return _read("system_logs", level, args, lambda: {"minutes": minutes, "level": level, "process": process, "lines": host().system_logs(minutes, level, process, limit)})


# ---------------------------------------------------------------------------------------------
# system_os
# ---------------------------------------------------------------------------------------------

SYSTEM_OS_SCHEMA = _schema(
    "system_os",
    "Hermes OS Linux's control surface: the same `hermes-os` commands the user's hotkeys and menu run. "
    "Software: install_app (name: a dnf package or Flatpak id), install_webapp (name, url, icon_url?: pins a website as an app), remove_app, remove_webapp. "
    "Reminders: reminder (duration like 20m or 1h30m, message), reminders_list, reminders_clear. "
    "notice (kind=time|battery|weather) shows a status notice. screenshot captures the screen and hands it to Hermes; ocr reads the text on screen. "
    "lock locks the session; suspend puts the computer to sleep. Themes: theme_list, theme_set (name), theme_current. update updates Hermes OS. "
    "Hermes shell: show_page (page: overview, hermes, missions, memory, files, automations, connections, settings), open_window (window=terminal|system|chat-popout), launch (name: an installed app), notify (title, body?). "
    "Spaces: focus_workspace (name), close_focused_window. install/remove/update and suspend ask the user to confirm. "
    "Only available on Hermes OS Linux; on macOS this tool is unavailable (use system_open / system_control instead).",
    {
        "action": _enum(
            "install_app", "install_webapp", "remove_app", "remove_webapp",
            "reminder", "reminders_list", "reminders_clear", "notice",
            "screenshot", "ocr", "lock", "suspend",
            "theme_list", "theme_set", "theme_current", "update",
            "show_page", "open_window", "launch", "notify",
            "focus_workspace", "close_focused_window",
            description="What to do.",
        ),
        "name": _desc(_STR, "For install_app / remove_app (package or Flatpak id), install_webapp / remove_webapp (web app name), theme_set (theme name), launch (app name or desktop id), focus_workspace (Space name)."),
        "url": _desc(_STR, "For install_webapp: the site to pin (http:// or https://)."),
        "icon_url": _desc(_STR, "For install_webapp: optional icon image URL (http:// or https://)."),
        "duration": _desc(_STR, "For reminder: how long from now, e.g. 90s, 20m, 1h, 1h30m, or a plain number of minutes."),
        "message": _desc(_STR, "For reminder: what to remind the user about."),
        "kind": _enum("time", "battery", "weather", description="For notice."),
        "page": _desc(_STR, "For show_page: the Hermes page id (overview, hermes, missions, memory, files, automations, connections, settings)."),
        "window": _enum("terminal", "system", "chat-popout", description="For open_window."),
        "title": _desc(_STR, "For notify."),
        "body": _desc(_STR, "For notify: optional body text."),
    },
    required=("action",),
)

HERMES_OS_BIN = "hermes-os"
_LONG_RUNNING_OS_ACTIONS = frozenset({"install_app", "install_webapp", "remove_app", "update"})
_OS_TIMEOUT_LONG = 1200.0
_OS_TIMEOUT_SHORT = 60.0
_OS_OUTPUT_LIMIT = 4000
_DURATION = re.compile(r"^\d+(s|m|h)(\d+(m|s))?$")

SYSTEM_OS_TIERS: dict[str, Tier] = {
    "theme_list": Tier.READ, "theme_current": Tier.READ, "reminders_list": Tier.READ, "notice": Tier.READ,
    "show_page": Tier.READ, "open_window": Tier.READ, "focus_workspace": Tier.READ,
    "launch": Tier.ACT, "notify": Tier.ACT, "screenshot": Tier.ACT, "ocr": Tier.ACT, "lock": Tier.ACT,
    "reminder": Tier.ACT, "theme_set": Tier.ACT, "close_focused_window": Tier.ACT,
    "install_app": Tier.MUTATE, "install_webapp": Tier.MUTATE, "remove_webapp": Tier.MUTATE, "reminders_clear": Tier.MUTATE, "update": Tier.MUTATE,
    "remove_app": Tier.DESTRUCTIVE, "suspend": Tier.DESTRUCTIVE,
}


def _os_arg(args: dict[str, Any], key: str, label: str | None = None) -> str:
    """A required free-text argument: non-empty and not shaped like a CLI flag."""
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required for action={label or args.get('action')}")
    if value.startswith("-"):
        raise ValueError(f"{key} must not start with '-'")
    return value


def _os_url(args: dict[str, Any], key: str, required: bool) -> str | None:
    value = str(args.get(key) or "").strip()
    if not value:
        if required:
            raise ValueError(f"{key} is required for action={args.get('action')}")
        return None
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError(f"{key} must start with http:// or https://")
    return value


def normalise_duration(raw: Any) -> str:
    """Accept ``90s`` / ``20m`` / ``1h`` / ``1h30m`` or a plain number of minutes (pure; tested)."""
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        raise ValueError("duration is required for action=reminder")
    if text.isdigit():
        if int(text) <= 0:
            raise ValueError("duration must be positive")
        return f"{int(text)}m"
    if not _DURATION.match(text):
        raise ValueError("duration must look like 90s, 20m, 1h or 1h30m (or a plain number of minutes)")
    return text


def plan_system_os(args: dict[str, Any]) -> tuple[list[str], str]:
    """Map the tool arguments to a ``hermes-os`` argv and a human summary (pure; tested).

    Raises ``ValueError`` for unknown actions and invalid or missing arguments."""
    action = str(args.get("action") or "")
    if action == "install_app":
        name = _os_arg(args, "name")
        return ["install", "app", name], f"install app {name}"
    if action == "install_webapp":
        name, url, icon = _os_arg(args, "name"), _os_url(args, "url", True), _os_url(args, "icon_url", False)
        return ["install", "webapp", name, url, *([icon] if icon else [])], f"install web app {name} ({url})"  # type: ignore[list-item]
    if action == "remove_app":
        name = _os_arg(args, "name")
        return ["remove", "app", name], f"remove app {name}"
    if action == "remove_webapp":
        name = _os_arg(args, "name")
        return ["remove", "webapp", name], f"remove web app {name}"
    if action == "reminder":
        duration = normalise_duration(args.get("duration"))
        message = _os_arg(args, "message")
        return ["reminder", duration, message], f"remind in {duration}: {truncate(message, 60)}"
    if action == "reminders_list":
        return ["reminder", "list"], "list reminders"
    if action == "reminders_clear":
        return ["reminder", "clear"], "clear all reminders"
    if action == "notice":
        kind = str(args.get("kind") or "").strip().lower()
        if kind not in ("time", "battery", "weather"):
            raise ValueError("kind must be one of time, battery, weather")
        return ["notice", kind], f"show the {kind} notice"
    if action == "screenshot":
        return ["screenshot"], "take a screenshot"
    if action == "ocr":
        return ["ocr"], "read the text on screen (OCR)"
    if action == "lock":
        return ["lock"], "lock the session"
    if action == "suspend":
        return ["suspend"], "suspend the computer"
    if action == "theme_list":
        return ["theme", "list"], "list themes"
    if action == "theme_set":
        name = _os_arg(args, "name")
        return ["theme", "set", name], f"set theme {name}"
    if action == "theme_current":
        return ["theme", "current"], "show the current theme"
    if action == "update":
        return ["update"], "update Hermes OS"
    if action == "show_page":
        page = _os_arg(args, "page")
        return ["page", page], f"show the {page} page"
    if action == "open_window":
        window = str(args.get("window") or "").strip().lower()
        if window not in ("terminal", "system", "chat-popout"):
            raise ValueError("window must be one of terminal, system, chat-popout")
        return ["open", window], f"open the {window} window"
    if action == "launch":
        name = _os_arg(args, "name")
        return ["launch", name], f"launch {name}"
    if action == "notify":
        title = _os_arg(args, "title")
        body = str(args.get("body") or "").strip()
        return ["notify", title, *([body] if body else [])], f"notify: {title}"
    if action == "focus_workspace":
        name = _os_arg(args, "name")
        return ["wm", "focus-workspace", name], f"focus Space {name}"
    if action == "close_focused_window":
        return ["wm", "close-window"], "close the focused window"
    raise ValueError(f"unknown action '{action}'")


def system_os_handler(args: dict[str, Any], **_: Any) -> str:
    if host().platform != "linux":
        return fail("system_os is only available on Hermes OS Linux")
    action = str(args.get("action") or "")
    try:
        cli_args, summary = plan_system_os(args)
    except ValueError as exc:
        return fail(str(exc))
    tier = SYSTEM_OS_TIERS[action]
    timeout = _OS_TIMEOUT_LONG if action in _LONG_RUNNING_OS_ACTIONS else _OS_TIMEOUT_SHORT
    argv = [HERMES_OS_BIN, *cli_args]

    def execute() -> dict[str, Any]:
        result = run(argv, timeout=timeout)
        if result.code == 127:
            raise HostNotSupported("The hermes-os command is not installed (it ships with Hermes OS Linux as /usr/local/bin/hermes-os).")
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"hermes-os exited {result.code}")
        return {"action": action, "output": truncate(result.stdout.strip(), _OS_OUTPUT_LIMIT)}

    return _guarded("system_os", tier, action, summary, args, (), execute)


handle_system_os = system_os_handler


# ---------------------------------------------------------------------------------------------

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("system_network", SYSTEM_NETWORK_SCHEMA, handle_system_network, "📶"),
    ToolSpec("system_control", SYSTEM_CONTROL_SCHEMA, handle_system_control, "🎛️"),
    ToolSpec("system_logs", SYSTEM_LOGS_SCHEMA, handle_system_logs, "📜"),
    ToolSpec("system_info", SYSTEM_INFO_SCHEMA, handle_system_info, "🖥️"),
    ToolSpec("system_processes", SYSTEM_PROCESSES_SCHEMA, handle_system_processes, "📈"),
    ToolSpec("system_disk_usage", SYSTEM_DISK_USAGE_SCHEMA, handle_system_disk_usage, "💽"),
    ToolSpec("system_find_files", SYSTEM_FIND_FILES_SCHEMA, handle_system_find_files, "🔍"),
    ToolSpec("system_apps", SYSTEM_APPS_SCHEMA, handle_system_apps, "🧩"),
    ToolSpec("system_open", SYSTEM_OPEN_SCHEMA, handle_system_open, "↗️"),
    ToolSpec("system_kill_process", SYSTEM_KILL_PROCESS_SCHEMA, handle_system_kill_process, "⛔"),
    ToolSpec("system_files", SYSTEM_FILES_SCHEMA, handle_system_files, "🗂️"),
    ToolSpec("system_os", SYSTEM_OS_SCHEMA, system_os_handler, "🐧"),
)

__all__ = ["TOOL_SPECS", "ToolSpec", "bridge_enabled", "normalise_duration", "plan_operations", "plan_system_os", "resolve_when", "system_os_handler", "json"]
