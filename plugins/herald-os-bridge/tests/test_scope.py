"""The tools are offered and run only in Herald OS's own sessions, whatever the configuration says."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types

import pytest


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge." + name)


class Ctx:
    def __init__(self):
        self.tools: dict[str, dict] = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_skill(self, name, path, description=""):
        pass


@pytest.fixture
def session(monkeypatch):
    """Hermes's ``gateway.session_context``: a bound turn sets every variable (unnamed ones to ""),
    which hides the process environment; with nothing bound the environment answers."""
    state: dict = {"bound": None}
    package = types.ModuleType("gateway")
    package.__path__ = []
    module = types.ModuleType("gateway.session_context")

    def get_session_env(name, default=""):
        if state["bound"] is not None:
            return state["bound"].get(name, "")
        return os.environ.get(name, default)

    module.get_session_env = get_session_env
    monkeypatch.setitem(sys.modules, "gateway", package)
    monkeypatch.setitem(sys.modules, "gateway.session_context", module)
    for name in ("HERALD_OS", "HERMES_KANBAN_TASK", "HERMES_SESSION_SOURCE", "HERMES_SESSION_PLATFORM", "HERMES_CRON_SESSION", "HERALD_OS_BRIDGE_DISABLED", "HERMES_OS_BRIDGE_DISABLED"):
        monkeypatch.delenv(name, raising=False)

    def bind(env: dict[str, str], bound: dict[str, str] | None) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        state["bound"] = bound

    return bind


@pytest.fixture
def registered(plugin):
    ctx = Ctx()
    plugin.register(ctx)
    return ctx.tools


HERALD_BACKEND = {"HERALD_OS": "1"}

# name -> (process environment, variables bound for the turn or None, tools offered, calls run)
CONTEXTS = {
    "a Herald OS turn": ({}, {"HERMES_SESSION_SOURCE": "herald_os"}, True, True),
    "a session saved before the rename": ({}, {"HERMES_SESSION_SOURCE": "hermes_os"}, True, True),
    "Telegram in the person's gateway": ({}, {"HERMES_SESSION_PLATFORM": "telegram"}, False, False),
    # A gateway the backend starts inherits HERALD_OS=1; a leaked source in its environment is hidden by the bound turn.
    "Telegram in a gateway Herald OS's backend started": ({**HERALD_BACKEND, "HERMES_SESSION_SOURCE": "herald_os"}, {"HERMES_SESSION_PLATFORM": "telegram"}, False, False),
    "cron in Herald OS's backend": (HERALD_BACKEND, {"HERMES_CRON_SESSION": "1"}, False, False),
    "the API server": (HERALD_BACKEND, {"HERMES_SESSION_PLATFORM": "api_server"}, False, False),
    "the hermes CLI": ({}, None, False, False),
    "the Hermes TUI": ({}, {"HERMES_SESSION_SOURCE": "tui"}, False, False),
    "Hermes Desktop": ({}, {"HERMES_SESSION_SOURCE": "desktop"}, False, False),
    "a kanban worker the backend started": ({**HERALD_BACKEND, "HERMES_KANBAN_TASK": "t_1"}, None, False, False),
    "Herald OS's backend between turns": (HERALD_BACKEND, None, True, False),
    "an eager resume in Herald OS's backend": (HERALD_BACKEND, {"HERMES_SESSION_SOURCE": "desktop"}, True, False),
    "a process a Herald OS session started": ({**HERALD_BACKEND, "HERMES_SESSION_SOURCE": "herald_os"}, None, True, True),
}


@pytest.mark.parametrize("name", list(CONTEXTS))
def test_tools_are_offered_and_run_only_for_herald_os(name, plugin, registered, session, tmp_path):
    env, bound, offered, runs = CONTEXTS[name]
    session(env, bound)
    assert plugin._check_available() is offered

    result = json.loads(registered["system_files"]["handler"]({"action": "mkdir", "path": str(tmp_path / "plan"), "dry_run": True}))
    assert result["success"] is runs, result
    if not runs:
        assert result["decision"] == "outside_herald" and "Herald OS" in result["error"]


def test_every_tool_is_registered_gated(plugin, registered):
    tools = _mod(plugin, "tools")
    assert list(registered) == [spec.name for spec in tools.TOOL_SPECS]
    for spec in tools.TOOL_SPECS:
        entry = registered[spec.name]
        assert entry["toolset"] == "herald_os" and entry["check_fn"] is plugin._check_available
        assert entry["handler"] is not spec.handler and entry["handler"].__wrapped__ is spec.handler


def test_a_refused_call_does_nothing_and_is_audited(plugin, registered, session, tmp_path, monkeypatch, isolated_home):
    perm = _mod(plugin, "permissions")
    monkeypatch.setattr(perm, "_confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a refused call must not ask")))
    session(HERALD_BACKEND, {"HERMES_SESSION_PLATFORM": "telegram"})
    target = tmp_path / "nope"

    result = json.loads(registered["system_files"]["handler"]({"action": "mkdir", "path": str(target)}))

    assert not result["success"] and "telegram" in result["error"]
    assert not target.exists()
    entry = json.loads((isolated_home / "herald-os" / "audit.jsonl").read_text().strip().splitlines()[-1])
    assert entry["tool"] == "system_files" and entry["decision"] == "outside_herald" and entry["ok"] is False


def test_a_call_without_a_session_in_the_backend_points_at_hermes_update(registered, session):
    session(HERALD_BACKEND, None)
    result = json.loads(registered["system_info"]["handler"]({}))
    assert not result["success"] and "hermes update" in result["error"]


def test_switching_the_bridge_off_stops_calls_in_herald_sessions_too(plugin, registered, session, monkeypatch):
    session({}, {"HERMES_SESSION_SOURCE": "herald_os"})
    monkeypatch.setenv("HERALD_OS_BRIDGE_DISABLED", "1")
    assert plugin._check_available() is False
    result = json.loads(registered["system_info"]["handler"]({}))
    assert not result["success"] and result["decision"] == "disabled" and "switched off" in result["error"]


def test_the_verdict_is_not_cached_across_sessions(plugin, monkeypatch):
    uncached = set()
    package = types.ModuleType("tools")
    package.__path__ = []
    registry = types.ModuleType("tools.registry")
    registry.no_cache_check_fn = lambda fn: uncached.add(fn) or fn
    monkeypatch.setitem(sys.modules, "tools", package)
    monkeypatch.setitem(sys.modules, "tools.registry", registry)

    plugin.register(Ctx())

    assert plugin._check_available in uncached
