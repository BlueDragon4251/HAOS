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


def test_text_shape_and_canvas_actions_pass_their_arguments(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "add_text", "content": "Night market", "x": 72, "y": 900, "font": "Helvetica Neue Bold", "size": 120, "align": "center", "source": "x.png"})
    assert command == "canvas.addText"
    assert args == {"content": "Night market", "x": 72, "y": 900, "font": "Helvetica Neue Bold", "size": 120, "align": "center"}
    _, command, args = tools.canvas_command({"action": "set_text", "layer": "Headline", "color": "#fff", "kind": "line"})
    assert (command, args) == ("canvas.setText", {"layer": "Headline", "color": "#fff"})
    _, command, args = tools.canvas_command({"action": "add_shape", "kind": "rounded", "width": 300, "height": 80, "radius": 40, "lineWidth": 2, "content": "no"})
    assert (command, args) == ("canvas.addShape", {"kind": "rounded", "width": 300, "height": 80, "radius": 40, "lineWidth": 2})
    _, command, args = tools.canvas_command({"action": "resize", "width": 1080, "height": 1080, "anchor": "top", "x": 3})
    assert (command, args) == ("canvas.resize", {"width": 1080, "height": 1080, "anchor": "top"})
    _, command, args = tools.canvas_command({"action": "resize", "scale": 0.5, "resample": False})
    assert args == {"scale": 0.5, "resample": False}
    _, command, args = tools.canvas_command({"action": "crop", "x": 0, "y": 100, "width": 1080, "height": 1350})
    assert (command, args) == ("canvas.crop", {"x": 0, "y": 100, "width": 1080, "height": 1350})


def test_the_schema_offers_every_action_and_argument(plugin):
    tools = _mod(plugin, "tools")
    properties = tools.CANVAS_SCHEMA["parameters"]["properties"]
    assert set(tools.CANVAS_ACTIONS) <= set(properties["action"]["enum"])
    for action, names in tools.CANVAS_ARGS.items():
        for name in names:
            assert name in properties, f"{action} passes {name}, which the schema does not describe"
    assert properties["size"]["type"] == "number"


def test_adjustment_settings_travel_as_json(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "add_adjustment", "kind": "Hue/Saturation", "settings": {"saturation": 20}})
    assert command == "canvas.addAdjustment"
    assert json.loads(args["settings"]) == {"saturation": 20}
    _, command, args = tools.canvas_command({"action": "set_adjustment", "layer": "Warmth", "settings": {"midCyanRed": 12}, "opacity": 0.6, "kind": "Levels"})
    assert command == "canvas.setAdjustment"
    assert json.loads(args.pop("settings")) == {"midCyanRed": 12}
    assert args == {"layer": "Warmth", "opacity": 0.6}


def test_effects_travel_as_json_and_may_clear_first(plugin):
    tools = _mod(plugin, "tools")
    effects = {"shadow": {"distance": 12, "blur": 24, "opacity": 0.4}, "stroke": False}
    _, command, args = tools.canvas_command({"action": "set_effects", "layer": "Cut-out", "effects": effects, "clear": True, "size": 3})
    assert command == "canvas.setEffects"
    assert json.loads(args.pop("effects")) == effects
    assert args == {"layer": "Cut-out", "clear": True}
    # Effects written as JSON text by the model pass through as they are.
    _, _, args = tools.canvas_command({"action": "set_effects", "layer": "Title", "effects": '{"outerGlow": {"size": 30}}'})
    assert args["effects"] == '{"outerGlow": {"size": 30}}'


def test_a_mask_action_travels_as_the_command_action(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "mask", "layer": "Photo", "mask": "hideSelection", "settings": {"x": 1}})
    assert (command, args) == ("canvas.mask", {"layer": "Photo", "action": "hideSelection"})
    properties = tools.CANVAS_SCHEMA["parameters"]["properties"]
    assert "revealSelection" in properties["mask"]["enum"] and "unlink" in properties["mask"]["enum"]
    assert properties["effects"]["type"] == "object"


def test_on_device_tools_and_placing_a_picture_pass_their_arguments(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "remove_background", "layer": "Photo", "mode": "cutout", "threshold": 0.4, "feather": 2, "refine": False, "source": "x.png"})
    assert (command, args) == ("canvas.removeBackground", {"layer": "Photo", "mode": "cutout", "threshold": 0.4, "feather": 2, "refine": False})
    _, command, args = tools.canvas_command({"action": "content_fill", "x": 10, "y": 20, "width": 300, "height": 200, "newLayer": True, "sampling": "all", "mode": "mask"})
    assert (command, args) == ("canvas.contentFill", {"x": 10, "y": 20, "width": 300, "height": 200, "newLayer": True, "sampling": "all"})
    # place_image's mask file travels as `mask`, which the mask action's own name would otherwise take.
    _, command, args = tools.canvas_command({"action": "place_image", "project": "~/P.comp", "source": "/tmp/r.png", "x": 5, "y": 6, "width": 70, "height": 80, "fit": "cover", "mask_image": "/tmp/m.png", "name": "Fill", "mask": "hide"})
    assert command == "canvas.placeImage"
    assert args == {"project": "~/P.comp", "source": "/tmp/r.png", "x": 5, "y": 6, "width": 70, "height": 80, "fit": "cover", "mask": "/tmp/m.png", "name": "Fill"}
    properties = tools.CANVAS_SCHEMA["parameters"]["properties"]
    assert properties["mode"]["enum"] == ["mask", "cutout"] and properties["sampling"]["enum"] == ["around", "all"]
    assert {"place_image", "remove_background", "content_fill"} <= set(properties["action"]["enum"])


def test_set_shape_restyles_a_shape_layer(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "set_shape", "layer": "Date panel", "kind": "rounded", "color": "#ffb347", "radius": 24, "lineWidth": 3, "x": 10, "content": "no"})
    assert command == "canvas.setShape"
    assert args == {"layer": "Date panel", "kind": "rounded", "color": "#ffb347", "radius": 24, "lineWidth": 3}
    assert "set_shape" in tools.CANVAS_SCHEMA["parameters"]["properties"]["action"]["enum"]


def test_export_takes_a_layered_psd(plugin):
    tools = _mod(plugin, "tools")
    _, command, args = tools.canvas_command({"action": "export", "to": "~/Desktop/poster.psd", "format": "psd"})
    assert (command, args) == ("canvas.export", {"to": "~/Desktop/poster.psd", "format": "psd"})
    assert "psd" in tools.CANVAS_SCHEMA["parameters"]["properties"]["format"]["enum"]


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
