"""macOS host adapter built on the tools every Mac ships with: ``mdfind``, ``open``, ``lsof``,
``ps``, ``du``, ``osascript``, ``sw_vers``, ``sysctl``, ``vm_stat``, ``df``, ``pmset``."""

from __future__ import annotations

import os
import plistlib
import re
import signal
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Sequence

from ..util import run
from .base import AppInfo, FileSearch, FoundFile, HostAdapter, PortListener, ProcessRow

APP_DIRS = ("/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities", str(Path.home() / "Applications"))

# Spotlight metadata attribute queries per FileSearch.kind.
_KIND_QUERIES: dict[str, str] = {
    "image": 'kMDItemContentTypeTree == "public.image"',
    "screenshot": 'kMDItemIsScreenCapture == 1',
    "document": '(kMDItemContentTypeTree == "public.composite-content" || kMDItemContentTypeTree == "public.text" || kMDItemContentTypeTree == "com.microsoft.word.doc" || kMDItemContentTypeTree == "org.openxmlformats.wordprocessingml.document")',
    "pdf": 'kMDItemContentType == "com.adobe.pdf"',
    "video": 'kMDItemContentTypeTree == "public.movie"',
    "audio": 'kMDItemContentTypeTree == "public.audio"',
    "folder": 'kMDItemContentType == "public.folder"',
    "code": 'kMDItemContentTypeTree == "public.source-code"',
    "archive": 'kMDItemContentTypeTree == "public.archive"',
}


def _applescript_string(value: str) -> str:
    """Escape for interpolation inside an AppleScript double-quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _mdfind_date(value: str, end_of_day: bool) -> str:
    """Spotlight wants ``$time.iso(...)``; accept ISO dates or datetimes."""
    value = value.strip()
    try:
        if len(value) == 10:
            dt = datetime.fromisoformat(value)
            if end_of_day:
                dt = dt + timedelta(days=1)
        else:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid date '{value}' (use YYYY-MM-DD or ISO 8601)") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return f'$time.iso("{dt.strftime("%Y-%m-%dT%H:%M:%S")}")'


def build_mdfind_query(search: FileSearch) -> str:
    """Compose the Spotlight predicate for a structured search (pure; unit-tested)."""
    clauses: list[str] = []
    kind = search.kind or "any"
    if kind != "any":
        clauses.append(_KIND_QUERIES[kind])
    if search.name:
        name = search.name.replace('"', '\\"')
        clauses.append(f'kMDItemFSName == "*{name}*"cd')
    if search.extensions:
        exts = " || ".join(f'kMDItemFSName == "*.{e.lstrip(".")}"c' for e in search.extensions)
        clauses.append(f"({exts})")
    if search.since:
        clauses.append(f"kMDItemContentCreationDate >= {_mdfind_date(search.since, False)}")
    if search.until:
        clauses.append(f"kMDItemContentCreationDate < {_mdfind_date(search.until, True)}")
    if search.text:
        text = search.text.replace('"', '\\"')
        clauses.append(f'(kMDItemTextContent == "*{text}*"cd || kMDItemDisplayName == "*{text}*"cd)')
    if not clauses:
        raise ValueError("search needs at least one of: text, name, kind, since/until, extensions")
    return " && ".join(clauses)


def parse_ps(text: str) -> list[ProcessRow]:
    rows: list[ProcessRow] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(.*)$", line)
        if not match:
            continue
        rows.append(ProcessRow(
            pid=int(match[1]), ppid=int(match[2]), user=match[3], cpu_percent=float(match[4]),
            mem_percent=float(match[5]), rss_bytes=int(match[6]) * 1024, command=match[7].strip(),
        ))
    return rows


def parse_lsof(text: str, port: int) -> list[PortListener]:
    """Parse ``lsof -nP -iTCP:PORT -sTCP:LISTEN`` (and UDP) output."""
    out: list[PortListener] = []
    seen: set[tuple[int, int]] = set()
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        key = (pid, port)
        if key in seen:
            continue
        seen.add(key)
        out.append(PortListener(pid=pid, command=parts[0], user=parts[2], port=port, protocol=parts[7].lower()))
    return out


def parse_du(text: str) -> list[tuple[int, str]]:
    """``du -k`` lines -> (bytes, path)."""
    rows: list[tuple[int, str]] = []
    for line in text.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]) * 1024, parts[1]))
        except ValueError:
            continue
    return rows


class DarwinHost(HostAdapter):
    platform = "darwin"

    # --- read -------------------------------------------------------------------------------
    def system_info(self) -> dict[str, Any]:
        name = run(["sw_vers", "-productName"]).stdout.strip() or "macOS"
        version = run(["sw_vers", "-productVersion"]).stdout.strip()
        build = run(["sw_vers", "-buildVersion"]).stdout.strip()
        chip = run(["sysctl", "-n", "machdep.cpu.brand_string"]).stdout.strip()
        cores = run(["sysctl", "-n", "hw.ncpu"]).stdout.strip()
        mem_bytes = int(run(["sysctl", "-n", "hw.memsize"]).stdout.strip() or 0)
        vm = run(["vm_stat"]).stdout
        page = re.search(r"page size of (\d+)", vm)
        page_size = int(page[1]) if page else 16384

        def pages(label: str) -> int:
            m = re.search(rf"{label}:\s+(\d+)", vm)
            return int(m[1]) if m else 0

        used = (pages("Pages active") + pages("Pages wired down") + pages("Pages occupied by compressor")) * page_size
        load = run(["sysctl", "-n", "vm.loadavg"]).stdout.strip().strip("{} ").split()
        uptime = run(["sysctl", "-n", "kern.boottime"]).stdout
        boot = re.search(r"sec = (\d+)", uptime)
        uptime_s = int(datetime.now().timestamp() - int(boot[1])) if boot else None
        disks = []
        for line in run(["df", "-kP"]).stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and (parts[5] == "/" or parts[5].startswith("/Volumes/")):
                disks.append({"mount": parts[5], "total_bytes": int(parts[1]) * 1024, "used_bytes": int(parts[2]) * 1024, "free_bytes": int(parts[3]) * 1024})
        batt = run(["pmset", "-g", "batt"]).stdout
        battery = None
        m = re.search(r"(\d+)%;\s*([a-zA-Z ]+?);", batt)
        if m:
            battery = {"percent": int(m[1]), "state": m[2].strip()}
        return {
            "os": f"{name} {version}", "build": build, "hostname": os.uname().nodename, "arch": os.uname().machine,
            "chip": chip, "cpu_cores": int(cores or 0),
            "memory_total_bytes": mem_bytes, "memory_used_bytes": used,
            "load_average": [float(x) for x in load[:3]] if load else None,
            "uptime_seconds": uptime_s, "disks": disks, "battery": battery,
            "user": os.environ.get("USER"), "home": str(Path.home()),
        }

    def _ps(self) -> list[ProcessRow]:
        return parse_ps(run(["ps", "-Axo", "pid=,ppid=,user=,%cpu=,%mem=,rss=,comm="]).stdout)

    def list_processes(self, sort: Literal["cpu", "memory"], limit: int) -> list[ProcessRow]:
        rows = self._ps()
        rows.sort(key=(lambda r: r.cpu_percent) if sort == "cpu" else (lambda r: r.rss_bytes), reverse=True)
        return rows[:limit]

    def find_processes(self, name: str, limit: int) -> list[ProcessRow]:
        needle = name.lower()
        rows = [r for r in self._ps() if needle in r.command.lower()]
        rows.sort(key=lambda r: r.cpu_percent, reverse=True)
        return rows[:limit]

    def listeners_on_port(self, port: int) -> list[PortListener]:
        tcp = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"]).stdout
        udp = run(["lsof", "-nP", f"-iUDP:{port}"]).stdout
        return parse_lsof(tcp, port) + parse_lsof(udp, port)

    def disk_usage(self, path: Path, depth: int, limit: int, timeout: float) -> dict[str, Any]:
        result = run(["du", "-k", "-d", str(depth), str(path)], timeout=timeout)
        rows = parse_du(result.stdout)
        total = next((b for b, p in rows if p.rstrip("/") == str(path).rstrip("/")), None)
        children = sorted((r for r in rows if r[1].rstrip("/") != str(path).rstrip("/")), key=lambda r: r[0], reverse=True)
        return {
            "path": str(path), "total_bytes": total, "timed_out": result.code == 124,
            "entries": [{"path": p, "bytes": b} for b, p in children[:limit]],
            "note": "Sizes exclude items du could not read (permission denied)." if "Permission denied" in result.stderr else None,
        }

    def find_files(self, query: FileSearch) -> list[FoundFile]:
        predicate = build_mdfind_query(query)
        argv = ["mdfind"]
        if query.scope:
            argv += ["-onlyin", str(Path(os.path.expanduser(query.scope)))]
        argv.append(predicate)
        result = run(argv, timeout=30)
        found: list[FoundFile] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            if len(found) >= max(1, query.limit):
                break
            p = Path(line)
            try:
                st = p.stat()
                found.append(FoundFile(path=line, size=st.st_size, modified=datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), kind="folder" if p.is_dir() else "file"))
            except OSError:
                found.append(FoundFile(path=line))
        found.sort(key=lambda f: f.modified or "", reverse=True)
        return found

    def installed_apps(self) -> list[AppInfo]:
        apps: dict[str, AppInfo] = {}
        for directory in APP_DIRS:
            try:
                entries = sorted(os.listdir(directory))
            except OSError:
                continue
            for entry in entries:
                if entry.endswith(".app") and not entry.startswith("."):
                    name = entry[:-4]
                    apps.setdefault(name, AppInfo(name=name, path=os.path.join(directory, entry), bundle_id=self._bundle_id(os.path.join(directory, entry))))
        return sorted(apps.values(), key=lambda a: a.name.lower())

    @staticmethod
    def _bundle_id(app_path: str) -> str | None:
        try:
            with open(os.path.join(app_path, "Contents", "Info.plist"), "rb") as fh:
                return plistlib.load(fh).get("CFBundleIdentifier")
        except Exception:  # noqa: BLE001
            return None

    def running_apps(self) -> list[AppInfo]:
        script = 'tell application "System Events" to get {name, unix id} of (every application process whose background only is false)'
        result = run(["osascript", "-e", script], timeout=10)
        if not result.ok:
            return []
        # Output: "Finder, Safari, ..., 123, 456, ..." (names then pids).
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        half = len(parts) // 2
        names, pids = parts[:half], parts[half:]
        apps: list[AppInfo] = []
        for name, pid in zip(names, pids):
            try:
                apps.append(AppInfo(name=name, path="", running=True, pid=int(pid)))
            except ValueError:
                apps.append(AppInfo(name=name, path="", running=True))
        return apps

    # --- act --------------------------------------------------------------------------------
    def resolve_app(self, name: str) -> AppInfo | None:
        needle = name.strip().lower().removesuffix(".app")
        candidates = self.installed_apps()
        for app in candidates:
            if app.name.lower() == needle:
                return app
        for app in candidates:
            if needle in app.name.lower() or (app.bundle_id and needle == app.bundle_id.lower()):
                return app
        return None

    def open_app(self, name: str, args: Sequence[str] = ()) -> None:
        app = self.resolve_app(name)
        target = app.path if app else name
        result = run(["open", "-a", target, *(["--args", *args] if args else [])], timeout=20)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"could not open {name}")

    def open_url(self, url: str, app: str | None = None) -> None:
        argv = ["open"]
        if app:
            resolved = self.resolve_app(app)
            argv += ["-a", resolved.path if resolved else app]
        argv.append(url)
        result = run(argv, timeout=20)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"could not open {url}")

    def open_path(self, path: Path, app: str | None = None) -> None:
        argv = ["open"]
        if app:
            resolved = self.resolve_app(app)
            argv += ["-a", resolved.path if resolved else app]
        argv.append(str(path))
        result = run(argv, timeout=20)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"could not open {path}")

    def reveal(self, path: Path) -> None:
        result = run(["open", "-R", str(path)], timeout=20)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"could not reveal {path}")

    def quit_app(self, name: str, force: bool) -> None:
        app = self.resolve_app(name)
        label = app.name if app else name
        if force:
            result = run(["pkill", "-x", label], timeout=10)
        else:
            result = run(["osascript", "-e", f'tell application "{_applescript_string(label)}" to quit'], timeout=20)
        if not result.ok and result.code != 1:
            raise RuntimeError(result.stderr.strip() or f"could not quit {label}")

    # --- destructive ------------------------------------------------------------------------
    def kill(self, pid: int, force: bool) -> None:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)

    def trash(self, paths: Sequence[Path]) -> None:
        # Finder's trash keeps the operation reversible; never `rm`.
        items = ", ".join(f'POSIX file "{_applescript_string(str(p))}"' for p in paths)
        script = f'tell application "Finder" to delete {{{items}}}'
        result = run(["osascript", "-e", script], timeout=30)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or "Finder refused to move items to the Trash")

    def notify(self, title: str, body: str) -> None:
        script = f'display notification "{_applescript_string(body)}" with title "{_applescript_string(title)}"'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
