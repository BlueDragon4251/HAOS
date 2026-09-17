"""Contracts for the pure parts of the tool layer and the macOS parsers."""

from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge." + name)


def test_resolve_when_windows(plugin):
    tools = _mod(plugin, "tools")
    today = date(2026, 9, 17)  # a Thursday.
    assert tools.resolve_when("yesterday", today) == ("2026-09-16", "2026-09-16")
    assert tools.resolve_when("today", today) == ("2026-09-17", "2026-09-17")
    assert tools.resolve_when("this_week", today) == ("2026-09-14", "2026-09-17")
    assert tools.resolve_when("this_month", today) == ("2026-09-01", "2026-09-17")
    assert tools.resolve_when(None, today) == (None, None)


def test_plan_operations_normalises_batch_and_rejects_bad_ops(plugin):
    tools = _mod(plugin, "tools")
    ops = tools.plan_operations({"action": "batch", "operations": [
        {"op": "mkdir", "path": "~/Desktop/Sorted"},
        {"op": "move", "path": "~/Desktop/a.png", "to": "~/Desktop/Sorted"},
    ]})
    assert [o.op for o in ops] == ["mkdir", "move"]
    assert ops[0].path == Path.home() / "Desktop" / "Sorted"
    assert ops[1].to == Path.home() / "Desktop" / "Sorted"
    import pytest

    with pytest.raises(ValueError):
        tools.plan_operations({"action": "move", "path": "~/x"})
    with pytest.raises(ValueError):
        tools.plan_operations({"action": "batch", "operations": [{"op": "rm", "path": "~/x"}]})


def test_dry_run_never_touches_disk_or_asks(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    perm = _mod(plugin, "permissions")
    monkeypatch.setattr(perm, "_confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run must not prompt")))
    target = tmp_path / "new-folder"
    result = json.loads(tools.handle_system_files({"action": "mkdir", "path": str(target), "dry_run": True}))
    assert result["success"] and result["dry_run"]
    assert result["plan"] == [f"create folder {target}"]
    assert not target.exists()


def test_mkdir_applies_after_approval_and_audits(plugin, tmp_path, monkeypatch, isolated_home):
    tools = _mod(plugin, "tools")
    perm = _mod(plugin, "permissions")
    monkeypatch.setattr(perm, "_confirm", lambda *a, **k: perm.Decision(True, "approved"))
    target = tmp_path / "Projects" / "Herald"
    result = json.loads(tools.handle_system_files({"action": "mkdir", "path": str(target)}))
    assert result["success"], result
    assert target.is_dir()
    audit_lines = (isolated_home / "hermes-os" / "audit.jsonl").read_text().strip().splitlines()
    entry = json.loads(audit_lines[-1])
    assert entry["tool"] == "system_files" and entry["decision"] == "approved" and entry["ok"] is True


def test_denied_mutation_is_not_applied(plugin, tmp_path, monkeypatch):
    tools = _mod(plugin, "tools")
    perm = _mod(plugin, "permissions")
    monkeypatch.setattr(perm, "_confirm", lambda *a, **k: perm.Decision(False, "denied", "no"))
    target = tmp_path / "nope"
    result = json.loads(tools.handle_system_files({"action": "mkdir", "path": str(target)}))
    assert not result["success"] and result["decision"] == "denied"
    assert not target.exists()


def test_kill_refuses_critical_pids(plugin, monkeypatch):
    tools = _mod(plugin, "tools")
    result = json.loads(tools.handle_system_kill_process({"pid": 1}))
    assert not result["success"] and "critical" in result["error"]


def test_open_rejects_non_web_schemes(plugin):
    tools = _mod(plugin, "tools")
    result = json.loads(tools.handle_system_open({"target": "url", "url": "javascript:alert(1)"}))
    assert not result["success"]


def test_mdfind_query_for_yesterdays_screenshots(plugin):
    darwin = _mod(plugin, "host.darwin")
    base = _mod(plugin, "host.base")
    query = darwin.build_mdfind_query(base.FileSearch(kind="screenshot", since="2026-09-16", until="2026-09-16"))
    assert "kMDItemIsScreenCapture == 1" in query
    assert 'kMDItemContentCreationDate >= $time.iso("2026-09-16T00:00:00")' in query
    assert 'kMDItemContentCreationDate < $time.iso("2026-09-17T00:00:00")' in query


def test_mdfind_query_requires_a_clause(plugin):
    darwin = _mod(plugin, "host.darwin")
    base = _mod(plugin, "host.base")
    import pytest

    with pytest.raises(ValueError):
        darwin.build_mdfind_query(base.FileSearch())


def test_parse_ps_and_lsof(plugin):
    darwin = _mod(plugin, "host.darwin")
    rows = darwin.parse_ps("  512   1 sam  12.5  0.3  204800 /usr/bin/node\n 999 512 sam 0.0 0.0 1024 /bin/zsh -l\n")
    assert rows[0].pid == 512 and rows[0].name == "node" and rows[0].rss_bytes == 204800 * 1024
    assert rows[1].command == "/bin/zsh -l"
    lsof = "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nnode 512 sam 23u IPv6 0x1 0t0 TCP *:3000 (LISTEN)\nnode 512 sam 24u IPv4 0x2 0t0 TCP 127.0.0.1:3000 (LISTEN)\n"
    listeners = darwin.parse_lsof(lsof, 3000)
    assert [l.pid for l in listeners] == [512], "one row per pid even with dual-stack sockets"
    assert listeners[0].protocol == "tcp"
