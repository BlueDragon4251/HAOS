"""Tool schemas and handlers for the ``hermes_os`` toolset.

Every handler follows the same shape: validate arguments, decide the permission tier for the
requested action, ``authorize`` (protected paths first, then the tier policy / approval gate),
execute through the host adapter, and ``audit.record`` the outcome. Handlers return JSON strings.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from . import audit
from .host import HostNotSupported, host
from .host.base import FileSearch
from .permissions import Tier, authorize
from .util import expand, fail, ok, truncate

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
    "Open things for the user. target=app launches an application by name ('Open Safari'); target=url opens a URL (optionally in a specific browser); target=path opens a file or folder with its default app or a named app; target=reveal shows a file in Finder; target=editor opens a folder/file in a code editor (editor=vscode|cursor|xcode|zed|terminal), e.g. 'open this repo in VS Code'. Runs immediately; every call is audited.",
    {
        "target": _enum("app", "url", "path", "reveal", "editor"),
        "app": _desc(_STR, "Application name (for target=app, or the app to open a url/path with)."),
        "url": _desc(_STR, "For target=url."),
        "path": _desc(_STR, "For target=path / reveal / editor. Supports ~."),
        "editor": _enum("vscode", "cursor", "xcode", "zed", "terminal", "iterm", description="For target=editor (default vscode)."),
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
    if target == "url":
        url = str(args.get("url") or "").strip()
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
    "Organise files and folders on this Mac. action=mkdir creates a folder (path); action=move moves/renames one item (path -> to); action=trash moves items to the Trash (paths; never permanent deletion); action=batch applies a list of operations [{op: mkdir|move|trash, path, to}] in one confirmation, ideal for 'organise these files'. Set dry_run=true first to show the plan; the user confirms mutating actions once per batch.",
    {
        "action": _enum("mkdir", "move", "trash", "batch"),
        "path": _desc(_STR, "Target path for mkdir/move/trash."),
        "to": _desc(_STR, "Destination for move (a folder, or the new full path)."),
        "paths": {"type": "array", "items": _STR, "description": "For trash: several items."},
        "operations": {
            "type": "array",
            "description": "For batch: ordered operations.",
            "items": {"type": "object", "properties": {"op": _enum("mkdir", "move", "trash"), "path": _STR, "to": _STR}, "required": ["op", "path"]},
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
            if op not in ("mkdir", "move", "trash") or not raw.get("path"):
                raise ValueError(f"invalid operation {raw}")
            ops.append(FileOp(op, expand(str(raw["path"])), expand(str(raw["to"])) if raw.get("to") else None))
    elif action == "mkdir":
        if not args.get("path"):
            raise ValueError("path is required")
        ops.append(FileOp("mkdir", expand(str(args["path"]))))
    elif action == "move":
        if not args.get("path") or not args.get("to"):
            raise ValueError("path and to are required for move")
        ops.append(FileOp("move", expand(str(args["path"])), expand(str(args["to"]))))
    elif action == "trash":
        raw_paths = list(args.get("paths") or ([] if not args.get("path") else [args["path"]]))
        if not raw_paths:
            raise ValueError("paths (or path) is required for trash")
        ops.extend(FileOp("trash", expand(str(p))) for p in raw_paths)
    else:
        raise ValueError(f"unknown action '{action}'")
    for op in ops:
        if op.op == "move" and op.to is None:
            raise ValueError(f"move of {op.path} needs 'to'")
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
        if op.op in ("move", "trash") and not op.path.exists():
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
            elif op.op == "trash":
                adapter.trash([op.path])
            done.append(op.describe())
        return {"applied": done}

    touched = [p for op in ops for p in op.touched()]
    return _guarded("system_files", tier, "batch" if len(ops) > 1 else ops[0].op, summary, args, touched, execute)


# ---------------------------------------------------------------------------------------------

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("system_info", SYSTEM_INFO_SCHEMA, handle_system_info, "🖥️"),
    ToolSpec("system_processes", SYSTEM_PROCESSES_SCHEMA, handle_system_processes, "📈"),
    ToolSpec("system_disk_usage", SYSTEM_DISK_USAGE_SCHEMA, handle_system_disk_usage, "💽"),
    ToolSpec("system_find_files", SYSTEM_FIND_FILES_SCHEMA, handle_system_find_files, "🔍"),
    ToolSpec("system_apps", SYSTEM_APPS_SCHEMA, handle_system_apps, "🧩"),
    ToolSpec("system_open", SYSTEM_OPEN_SCHEMA, handle_system_open, "↗️"),
    ToolSpec("system_kill_process", SYSTEM_KILL_PROCESS_SCHEMA, handle_system_kill_process, "⛔"),
    ToolSpec("system_files", SYSTEM_FILES_SCHEMA, handle_system_files, "🗂️"),
)

__all__ = ["TOOL_SPECS", "ToolSpec", "bridge_enabled", "plan_operations", "resolve_when", "json"]
