"""The ``canvas`` tool: actions to canvas.* commands, the tier rules, and a call through the shell."""

from __future__ import annotations

import importlib
import json

import pytest


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge." + name)


CATALOGUE = [
    {"id": "canvas.addLayer", "title": "Add a layer", "tier": "act", "args": []},
    {"id": "canvas.addAdjustment", "title": "Add an adjustment layer", "tier": "act", "args": []},
    {"id": "canvas.export", "title": "Export an image", "tier": "act", "args": []},
    {"id": "canvas.save", "title": "Save an image", "tier": "mutate", "args": []},
    {"id": "canvas.preview", "title": "Look at an image", "tier": "read", "args": []},
]


@pytest.fixture
def shell(plugin, monkeypatch):
    tools = _mod(plugin, "tools")
    ui = _mod(plugin, "ui")
    perm = _mod(plugin, "permissions")
    calls: list[tuple[str, dict, float]] = []
    decisions: list[tuple[str, str, str]] = []

    def run_command(command, args=None, *, source="agent", timeout=12.0):
        calls.append((command, args or {}, timeout))
        if command == "canvas.preview":
            return {"ok": True, "summary": "Preview of Poster", "data": {"file": "/tmp/herald-canvas-previews/Poster.png"}}
        return {"ok": True, "summary": f"ran {command}", "data": {}}

    def authorize(tool, tier, action, summary, *, paths=()):
        decisions.append((tool, tier.value, action))
        return perm.Decision(True, "allowed")

    monkeypatch.setattr(ui, "run_command", run_command)
    monkeypatch.setattr(ui, "list_commands", lambda: CATALOGUE)
    monkeypatch.setattr(tools, "authorize", authorize)
    tools._UI_CATALOGUE.clear()
    yield calls, decisions
    tools._UI_CATALOGUE.clear()


def test_actions_map_to_commands_and_drop_stray_arguments(plugin):
    tools = _mod(plugin, "tools")
    action, command, args = tools.canvas_command({"action": "add_layer", "source": "~/a.png", "x": 10, "kind": "Levels", "name": ""})
    assert (action, command) == ("add_layer", "canvas.addLayer")
    assert args == {"source": "~/a.png", "x": 10}
    with pytest.raises(ValueError):
        tools.canvas_command({"action": "paint"})


def test_adjustment_settings_travel_as_json(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "add_adjustment", "kind": "Hue/Saturation", "settings": {"saturation": 20}})
    assert command == "canvas.addAdjustment"
    assert json.loads(args["settings"]) == {"saturation": 20}


def test_replacing_a_file_asks_first(plugin, tmp_path):
    tools = _mod(plugin, "tools")
    catalogue = {entry["id"]: entry for entry in CATALOGUE}
    existing = tmp_path / "poster.png"
    existing.write_bytes(b"png")
    new = str(tmp_path / "new.png")
    assert tools.canvas_tier("export", "canvas.export", {"to": new}, catalogue).value == "act"
    assert tools.canvas_tier("export", "canvas.export", {"to": str(existing)}, catalogue).value == "mutate"
    assert tools.canvas_tier("export", "canvas.export", {"to": new, "overwrite": True}, catalogue).value == "mutate"
    assert tools.canvas_tier("save", "canvas.save", {}, catalogue).value == "mutate"
    assert tools.canvas_tier("preview", "canvas.preview", {}, catalogue).value == "read"


def test_a_call_runs_in_the_shell_with_a_long_timeout(plugin, shell):
    tools = _mod(plugin, "tools")
    calls, decisions = shell
    reply = json.loads(tools.handle_canvas({"action": "preview", "project": "~/Pictures/Poster.comp", "size": 800}))
    assert reply["success"] is True
    assert reply["data"]["file"].endswith("Poster.png")
    assert calls[-1][0] == "canvas.preview" and calls[-1][1] == {"project": "~/Pictures/Poster.comp", "size": 800}
    assert calls[-1][2] >= 60
    assert decisions[-1] == ("canvas", "read", "preview")


def test_a_shell_without_canvas_says_so(plugin, shell, monkeypatch):
    tools = _mod(plugin, "tools")
    ui = _mod(plugin, "ui")
    monkeypatch.setattr(ui, "list_commands", lambda: [{"id": "page.open", "tier": "read"}])
    tools._UI_CATALOGUE.clear()
    reply = json.loads(tools.handle_canvas({"action": "status"}))
    assert reply["success"] is False and "update Herald OS" in reply["error"]
