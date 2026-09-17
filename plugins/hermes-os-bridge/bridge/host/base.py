"""The capability contract every platform adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence


class HostNotSupported(RuntimeError):
    """Raised by adapters for platforms Hermes OS does not implement yet."""


@dataclass
class ProcessRow:
    pid: int
    ppid: int
    user: str
    cpu_percent: float
    mem_percent: float
    rss_bytes: int
    command: str

    @property
    def name(self) -> str:
        return self.command.rsplit("/", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid, "ppid": self.ppid, "user": self.user, "name": self.name,
            "cpu_percent": self.cpu_percent, "mem_percent": self.mem_percent,
            "rss_bytes": self.rss_bytes, "command": self.command,
        }


@dataclass
class PortListener:
    pid: int
    command: str
    user: str
    port: int
    protocol: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class FoundFile:
    path: str
    size: int | None = None
    modified: str | None = None
    kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class FileSearch:
    """Structured search request; adapters translate it to the platform indexer."""

    text: str | None = None
    name: str | None = None
    kind: Literal["any", "image", "screenshot", "document", "pdf", "video", "audio", "folder", "code", "archive"] = "any"
    since: str | None = None     # ISO date / datetime, inclusive.
    until: str | None = None
    scope: str | None = None     # Directory to search under.
    extensions: Sequence[str] = field(default_factory=tuple)
    limit: int = 50


@dataclass
class AppInfo:
    name: str
    path: str
    bundle_id: str | None = None
    running: bool | None = None
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class HostAdapter(ABC):
    platform: str = "unknown"

    def available(self) -> bool:
        return True

    # --- read -------------------------------------------------------------------------------
    @abstractmethod
    def system_info(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_processes(self, sort: Literal["cpu", "memory"], limit: int) -> list[ProcessRow]: ...

    @abstractmethod
    def find_processes(self, name: str, limit: int) -> list[ProcessRow]: ...

    @abstractmethod
    def listeners_on_port(self, port: int) -> list[PortListener]: ...

    @abstractmethod
    def disk_usage(self, path: Path, depth: int, limit: int, timeout: float) -> dict[str, Any]: ...

    @abstractmethod
    def find_files(self, query: FileSearch) -> list[FoundFile]: ...

    @abstractmethod
    def installed_apps(self) -> list[AppInfo]: ...

    @abstractmethod
    def running_apps(self) -> list[AppInfo]: ...

    # --- act --------------------------------------------------------------------------------
    @abstractmethod
    def open_app(self, name: str, args: Sequence[str] = ()) -> None: ...

    @abstractmethod
    def open_url(self, url: str, app: str | None = None) -> None: ...

    @abstractmethod
    def open_path(self, path: Path, app: str | None = None) -> None: ...

    @abstractmethod
    def reveal(self, path: Path) -> None: ...

    @abstractmethod
    def quit_app(self, name: str, force: bool) -> None: ...

    # --- destructive ------------------------------------------------------------------------
    @abstractmethod
    def kill(self, pid: int, force: bool) -> None: ...

    @abstractmethod
    def trash(self, paths: Sequence[Path]) -> None: ...

    @abstractmethod
    def notify(self, title: str, body: str) -> None: ...
