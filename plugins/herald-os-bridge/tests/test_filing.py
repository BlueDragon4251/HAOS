"""Filing with ``system_files``: where a batch lands, clashes found before anything moves, the approval
line the person reads, and ``undo`` (including after a batch that stopped partway)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge." + name)


def _approve(plugin, monkeypatch, seen: list[str] | None = None):
    perm = _mod(plugin, "permissions")

    def confirm(tool, summary, rule_key):
        if seen is not None:
            seen.append(summary)
        return perm.Decision(True, "approved")

    monkeypatch.setattr(perm, "_confirm", confirm)


def _downloads(tmp_path: Path) -> tuple[Path, Path]:
    downloads = tmp_path / "Downloads"
    invoices = tmp_path / "Documents" / "Finances" / "Invoices" / "2026"
    downloads.mkdir(parents=True)
    invoices.mkdir(parents=True)
    (downloads / "scan0001.pdf").write_bytes(b"acme")
    (downloads / "scan0002.pdf").write_bytes(b"acme")
    (downloads / "IMG_2231.pdf").write_bytes(b"northwind")
    return downloads, invoices


def test_plan_targets_walks_the_batch_in_order(plugin, tmp_path):
    tools = _mod(plugin, "tools")
    downloads, invoices = _downloads(tmp_path)
    (invoices / "2026-08-02 Telstra invoice 9921.pdf").write_bytes(b"filed")
    year = invoices.parent / "2027"
    ops = tools.plan_operations({"action": "batch", "operations": [
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(invoices / "2026-09-14 Acme Corp invoice INV-1234.pdf")},
        {"op": "move", "path": str(downloads / "scan0002.pdf"), "to": str(invoices / "2026-09-14 Acme Corp invoice INV-1234.pdf")},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices / "2026-08-02 Telstra invoice 9921.pdf")},
        {"op": "mkdir", "path": str(year)},
        {"op": "copy", "path": str(downloads), "to": str(downloads / "inside")},
        {"op": "move", "path": str(downloads / "gone.pdf"), "to": str(year)},
    ]})
    targets, problems = tools.plan_targets(ops)
    assert targets[0] == invoices / "2026-09-14 Acme Corp invoice INV-1234.pdf"
    assert problems == [
        f"{invoices / '2026-09-14 Acme Corp invoice INV-1234.pdf'} already exists; not overwriting",
        f"{invoices / '2026-08-02 Telstra invoice 9921.pdf'} already exists; not overwriting",
        f"cannot put {downloads} inside itself",
        f"{downloads / 'gone.pdf'} does not exist",
    ], "a name taken earlier in the batch counts, and so does one already on disk"
    into_new_folder = tools.plan_targets(tools.plan_operations({"action": "batch", "operations": [
        {"op": "mkdir", "path": str(year)},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(year)},
    ]}))
    assert into_new_folder == ([None, year / "IMG_2231.pdf"], []), "a folder created earlier in the batch is a folder"


def test_dry_run_shows_where_files_land(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    perm = _mod(plugin, "permissions")
    monkeypatch.setattr(perm, "_confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a dry run never asks")))
    downloads, invoices = _downloads(tmp_path)
    result = json.loads(tools.handle_system_files({"action": "batch", "dry_run": True, "operations": [
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(downloads / "2026-09-14 Acme Corp invoice.pdf")},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices)},
    ]}))
    assert result["plan"] == [
        f"rename {downloads / 'scan0001.pdf'} -> 2026-09-14 Acme Corp invoice.pdf",
        f"move {downloads / 'IMG_2231.pdf'} -> {invoices / 'IMG_2231.pdf'}",
    ]
    assert result["problems"] == [] and (downloads / "scan0001.pdf").exists()


def test_filing_applies_once_approved_and_undo_puts_it_back(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    seen: list[str] = []
    _approve(plugin, monkeypatch, seen)
    monkeypatch.setenv("HOME", str(tmp_path))
    downloads, invoices = _downloads(tmp_path)
    year = invoices.parent / "2027"
    target = invoices / "2026-09-14 Acme Corp invoice INV-1234 $560.00.pdf"
    result = json.loads(tools.handle_system_files({"action": "batch", "operations": [
        {"op": "mkdir", "path": str(year)},
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(target)},
        {"op": "copy", "path": str(downloads / "IMG_2231.pdf"), "to": str(year)},
    ]}))
    assert result["success"], result
    assert target.read_bytes() == b"acme" and not (downloads / "scan0001.pdf").exists() and (year / "IMG_2231.pdf").exists()
    assert result["created_folders"] == [str(year)]
    assert result["undo"] == [
        {"op": "trash", "path": str(year / "IMG_2231.pdf")},
        {"op": "move", "path": str(target), "to": str(downloads / "scan0001.pdf")},
    ], "newest first, so it can run as one batch"
    assert seen[0].startswith("3 file operations: create folder ~/Documents/Finances/Invoices/2027; move ~/Downloads/scan0001.pdf -> ~/Documents/"), seen[0]
    moves_only = [op for op in result["undo"] if op["op"] == "move"]
    back = json.loads(tools.handle_system_files({"action": "batch", "operations": moves_only}))
    assert back["success"] and (downloads / "scan0001.pdf").read_bytes() == b"acme" and not target.exists()


def test_a_batch_that_stops_partway_reports_what_to_undo(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    _approve(plugin, monkeypatch)
    downloads, invoices = _downloads(tmp_path)
    real_move = tools.shutil.move
    calls = []

    def flaky_move(source, destination):
        calls.append(source)
        if len(calls) == 2:
            raise PermissionError("Operation not permitted")
        return real_move(source, destination)

    monkeypatch.setattr(tools.shutil, "move", flaky_move)
    result = json.loads(tools.handle_system_files({"action": "batch", "operations": [
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(invoices)},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices)},
    ]}))
    assert not result["success"] and "stopped after 1 of 2 operations" in result["error"]
    assert result["applied"] == [f"move {downloads / 'scan0001.pdf'} -> {invoices / 'scan0001.pdf'}"]
    assert result["undo"] == [{"op": "move", "path": str(invoices / "scan0001.pdf"), "to": str(downloads / "scan0001.pdf")}]


def test_nothing_moves_when_any_target_is_taken(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    _approve(plugin, monkeypatch)
    downloads, invoices = _downloads(tmp_path)
    (invoices / "IMG_2231.pdf").write_bytes(b"older")
    result = json.loads(tools.handle_system_files({"action": "batch", "operations": [
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(invoices)},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices)},
    ]}))
    assert not result["success"] and "already exists" in result["error"]
    assert (downloads / "scan0001.pdf").exists(), "checked before the first move, not halfway through"


def test_undo_replays_the_last_batch_of_the_conversation(plugin, tmp_path, monkeypatch, isolated_home):
    tools = _mod(plugin, "tools")
    seen: list[str] = []
    _approve(plugin, monkeypatch, seen)
    downloads, invoices = _downloads(tmp_path)
    target = invoices / "2026-09-14 Acme Corp invoice INV-1234 $560.00.pdf"
    filed = json.loads(tools.handle_system_files({"action": "batch", "operations": [
        {"op": "move", "path": str(downloads / "scan0001.pdf"), "to": str(target)},
        {"op": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices)},
    ]}, session_id="voice-1"))
    assert filed["success"] and filed["undo_id"]
    other = json.loads(tools.handle_system_files({"action": "undo"}, session_id="typed-2"))
    assert not other["success"] and "Nothing to undo" in other["error"], "another conversation's batch is not its to undo"
    plan = json.loads(tools.handle_system_files({"action": "undo", "dry_run": True}, session_id="voice-1"))
    assert plan["dry_run"] and plan["problems"] == [] and len(plan["plan"]) == 2 and target.exists()
    undone = json.loads(tools.handle_system_files({"action": "undo"}, session_id="voice-1"))
    assert undone["success"] and undone["undone"].startswith("2 file operations: move ")
    assert (downloads / "scan0001.pdf").read_bytes() == b"acme" and (downloads / "IMG_2231.pdf").exists() and not target.exists()
    audit = json.loads((isolated_home / "herald-os" / "audit.jsonl").read_text().strip().splitlines()[-1])
    assert audit["action"] == "undo" and audit["decision"] == "approved"
    again = json.loads(tools.handle_system_files({"action": "undo"}, session_id="voice-1"))
    assert not again["success"] and "Nothing to undo" in again["error"], "an undone batch is not undone twice"


def test_undo_steps_back_batch_by_batch_or_by_undo_id(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    _approve(plugin, monkeypatch)
    downloads, invoices = _downloads(tmp_path)
    first = json.loads(tools.handle_system_files({"action": "move", "path": str(downloads / "scan0001.pdf"), "to": str(invoices)}, session_id="s"))
    json.loads(tools.handle_system_files({"action": "move", "path": str(downloads / "IMG_2231.pdf"), "to": str(invoices)}, session_id="s"))
    json.loads(tools.handle_system_files({"action": "move", "path": str(downloads / "scan0002.pdf"), "to": str(invoices)}, session_id="s"))
    assert json.loads(tools.handle_system_files({"action": "undo"}, session_id="s"))["success"]
    assert (downloads / "scan0002.pdf").exists() and not (downloads / "IMG_2231.pdf").exists(), "the most recent batch first"
    assert json.loads(tools.handle_system_files({"action": "undo", "undo_id": first["undo_id"]}, session_id="s"))["success"]
    assert (downloads / "scan0001.pdf").exists() and (invoices / "IMG_2231.pdf").exists()
    missing = json.loads(tools.handle_system_files({"action": "undo", "undo_id": "nope"}, session_id="s"))
    assert not missing["success"] and "undo_id nope" in missing["error"]


def test_tilde_shortens_only_the_home_folder(plugin, monkeypatch, tmp_path):
    tools = _mod(plugin, "tools")
    monkeypatch.setenv("HOME", str(tmp_path / "sam"))
    assert tools.tilde(tmp_path / "sam" / "Documents") == "~/Documents"
    assert tools.tilde(tmp_path / "sam") == "~"
    assert tools.tilde(tmp_path / "samantha") == str(tmp_path / "samantha")
