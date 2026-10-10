import base64
import json
import time
import uuid

import pytest

from haos.gui import GuiBroker, action, receipt
from haos.store import Conflict, MissionStore
from haos.sandbox import command
from haos.redaction import Redactor


def key():
    return str(uuid.uuid4())


@pytest.fixture
def live(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    row = store.create("uid:4251", "gui", "use local browser")
    row = store.claim()
    store.session(row["id"], "runtime-session", "stored-session")
    store.dispatching(row["id"])
    gui = GuiBroker(store)
    epoch = key()
    gui.attach({"epoch": epoch})
    yield store, gui, row["id"], epoch
    store.close()


def submit(gui, mid, op=None, rid=None):
    return gui.submit(mid, {"session": "runtime-session", "id": rid or key(), "action": op or {"operation": "open", "html": "<input>"}})


def test_actual_queue_dispatch_ack_and_content_removal(live):
    store, gui, mid, epoch = live
    admitted = submit(gui, mid)
    poll = gui.poll(mid, {"epoch": epoch})
    assert poll["request"]["action"] == {"operation": "open", "html": "<input>"}
    assert gui.poll(mid, {"epoch": epoch})["request"] is None
    assert store.db.execute("SELECT arguments FROM gui_actions").fetchone()[0] is None
    result = {"window": key(), "width": 800, "height": 600}
    gui.acknowledge({"epoch": epoch, "id": admitted["id"], "ok": True, "result": result})
    assert gui.result(mid, {"session": "stored-session", "id": admitted["id"]}) == {**admitted, "state": "succeeded", "result": result}
    events = store.events(mid)
    assert [e["kind"] for e in events][-3:] == ["gui.admitted", "gui.dispatched", "gui.succeeded"]
    assert "<input>" not in json.dumps(events)


def test_replay_receipt_reopen_uncertainty_and_no_re_dispatch(live, tmp_path):
    store, gui, mid, epoch = live
    rid = key()
    submit(gui, mid, rid=rid)
    assert submit(gui, mid, rid=rid)["id"] == rid
    with pytest.raises(Conflict):
        submit(gui, mid, {"operation": "open", "html": "different"}, rid)
    gui.poll(mid, {"epoch": epoch})
    reopened = MissionStore(tmp_path / "missions.db")
    recovery = GuiBroker(reopened)
    recovery.attach({"epoch": key()})
    assert recovery.result(mid, {"session": "runtime-session", "id": rid})["state"] == "uncertain"
    assert recovery.poll(mid, {"epoch": recovery.epoch})["request"] is None
    assert submit(recovery, mid, rid=rid)["state"] == "uncertain"
    reopened.close()


@pytest.mark.parametrize("change", ["wrong-session", "queued", "waiting", "cancel", "deadline", "not-dispatched", "no-current"])
def test_mission_scope_denials(live, change):
    store, gui, mid, epoch = live
    session = "runtime-session"
    if change == "wrong-session":
        session = "other"
    elif change in {"queued", "waiting"}:
        store.db.execute("UPDATE missions SET state=? WHERE id=?", (change, mid))
    elif change == "cancel":
        store.request_cancel(mid, "uid:4251")
    elif change == "deadline":
        store.db.execute("UPDATE missions SET deadline=0 WHERE id=?", (mid,))
    elif change == "not-dispatched":
        store.db.execute("UPDATE missions SET phase='connecting' WHERE id=?", (mid,))
    elif change == "no-current":
        mid = None
    with pytest.raises(PermissionError):
        gui.submit(mid, {"session": session, "id": key(), "action": {"operation": "state"}})


@pytest.mark.parametrize("data", [
    {"operation": "open", "html": "ok", "url": "file:///etc/shadow"},
    {"operation": "shell", "command": "sudo"}, {"operation": "clipboard"},
    {"operation": "capture", "window": "42"},
    {"operation": "capture", "window": "../owner"},
    {"operation": "click", "window": str(uuid.UUID(int=1)), "x": 40, "y": 1},
    {"operation": "click", "window": str(uuid.UUID(int=1)), "x": True, "y": 50},
    {"operation": "type", "window": str(uuid.UUID(int=1)), "text": "\n"},
    {"operation": "key", "window": str(uuid.UUID(int=1)), "key": "Control+V"},
    {"operation": "open", "html": "é" * 20000}, {"operation": "state", "mission": "owner"},
    {"operation": "open", "html": '<IFRAME srcdoc="nested"></IFRAME>'},
    {"operation": "scroll", "window": str(uuid.UUID(int=1)), "x": 40, "y": 60, "deltaX": 0, "deltaY": 553},
    {"operation": "scroll", "window": str(uuid.UUID(int=1)), "x": 40, "y": 60, "deltaX": True, "deltaY": 100},
    {"operation": "scroll", "window": str(uuid.UUID(int=1)), "x": 40, "y": 60, "deltaX": 0, "deltaY": 0},
    {"operation": "read", "window": str(uuid.UUID(int=1)), "selector": "owner"},
])
def test_host_privilege_clipboard_and_parameter_denials(data):
    with pytest.raises((ValueError, PermissionError)):
        action(data)


def test_stale_native_epoch_and_late_receipt_do_not_replay(live):
    store, gui, mid, epoch = live
    admitted = submit(gui, mid)
    gui.poll(mid, {"epoch": epoch})
    replacement = key()
    gui.attach({"epoch": replacement})
    with pytest.raises(PermissionError):
        gui.poll(mid, {"epoch": epoch})
    with pytest.raises(PermissionError):
        gui.acknowledge({"epoch": epoch, "id": admitted["id"], "ok": False, "result": {}})
    assert gui.poll(mid, {"epoch": replacement})["request"] is None
    assert gui.result(mid, {"session": "runtime-session", "id": admitted["id"]})["state"] == "uncertain"


def test_expired_action_and_detached_native_deny(live):
    store, gui, mid, epoch = live
    admitted = submit(gui, mid)
    store.db.execute("UPDATE gui_actions SET created_at=0")
    assert gui.poll(mid, {"epoch": epoch})["request"] is None
    assert gui.result(mid, {"session": "runtime-session", "id": admitted["id"]})["state"] == "uncertain"
    gui.seen_at = 0
    with pytest.raises(Conflict):
        submit(gui, mid)


def test_capture_is_ephemeral_not_ledger_or_audit(live):
    store, gui, mid, epoch = live
    # Protocol fixture only; actual pixel capture is tested by the separate Chromium gate.
    image = b"\xff\xd8" + b"disposable-image-fixture" * 8 + b"\xff\xd9"
    rid = submit(gui, mid, {"operation": "capture", "window": key()})["id"]
    gui.poll(mid, {"epoch": epoch})
    data = {"window": key(), "width": 800, "height": 600, "jpeg": base64.b64encode(image).decode()}
    gui.acknowledge({"epoch": epoch, "id": rid, "ok": True, "result": data})
    assert gui.result(mid, {"session": "runtime-session", "id": rid})["result"]["jpeg"] == data["jpeg"]
    assert data["jpeg"] not in json.dumps(store.events(mid))
    assert data["jpeg"] not in store.db.execute("SELECT result FROM gui_actions").fetchone()[0]
    gui.images[rid] = (time.time() - 16, data)
    result = gui.result(mid, {"session": "runtime-session", "id": rid})
    assert "jpeg" not in result["result"] and result["result"]["capture_available"] is False


def test_budget_and_oversized_forged_receipts(live):
    store, gui, mid, epoch = live
    for _ in range(120):
        submit(gui, mid, {"operation": "state"})
    with pytest.raises(Conflict):
        submit(gui, mid)
    with pytest.raises(ValueError):
        receipt("capture", {"window": key(), "width": 800, "height": 600, "jpeg": "A" * 98305})
    with pytest.raises(ValueError):
        receipt("state", {"windows": [{"window": key(), "width": 800, "height": 600, "credential": "private"}]})


def test_gui_binding_is_only_fixed_read_only_directory():
    args = command([], 3, certificates=[], gui=True)
    index = args.index("/run/haos-gui-agent")
    assert args[index - 1:index + 2] == ["--ro-bind", "/run/haos-gui-agent", "/run/haos-gui-agent"]
    assert "/run/haos-control" not in args and "WAYLAND_DISPLAY" not in args and "NIRI_SOCKET" not in args


def test_inspection_receipt_ephemeral_and_sensitive_fields_denied(live):
    store, gui, mid, epoch = live
    rid = submit(gui, mid, {"operation": "inspect", "window": key()})["id"]
    gui.poll(mid, {"epoch": epoch})
    data = {"window": key(), "fields": [{"index": 12, "name": "actual-field", "type": "text", "value": "private-form-value", "truncated": False, "sensitive": False}]}
    gui.acknowledge({"epoch": epoch, "id": rid, "ok": True, "result": data})
    assert gui.result(mid, {"session": "runtime-session", "id": rid})["result"] == data
    assert "private-form-value" not in json.dumps(store.events(mid))
    assert "private-form-value" not in store.db.execute("SELECT result FROM gui_actions").fetchone()[0]
    gui.images[rid] = (0, data)
    result = gui.result(mid, {"session": "runtime-session", "id": rid})["result"]
    assert "fields" not in result and result["inspection_available"] is False
    data["fields"][0].update(type="password", sensitive=True)
    with pytest.raises(PermissionError):
        receipt("inspect", data)
    data["fields"][0]["value"] = "[redacted]"
    assert receipt("inspect", data) == data


@pytest.mark.parametrize("alter", ["duplicate", "extra", "oversized", "unmarked-password"])
def test_inspection_result_validation(alter):
    field = {"index": 1, "name": "field", "type": "text", "value": "value", "truncated": False, "sensitive": False}
    fields = [field]
    if alter == "duplicate":
        fields.append(dict(field))
    elif alter == "extra":
        field["credentials"] = "private"
    elif alter == "oversized":
        field["value"] = "x" * 513
    else:
        field["type"] = "password"
    with pytest.raises((ValueError, PermissionError)):
        receipt("inspect", {"window": key(), "fields": fields})


def test_read_text_redacted_ephemeral_and_excluded_from_persistent_ledger(live):
    store, gui, mid, epoch = live
    store.redactor = Redactor(['DISPOSABLE_SECRET_CANARY'])
    rid = submit(gui, mid, {"operation": "read", "window": key()})["id"]
    gui.poll(mid, {"epoch": epoch})
    data = {"window": key(), "text": "Private visible text DISPOSABLE_SECRET_CANARY", "truncated": False}
    gui.acknowledge({"epoch": epoch, "id": rid, "ok": True, "result": data})
    result = gui.result(mid, {"session": "runtime-session", "id": rid})["result"]
    assert 'Private visible text' in result['text'] and 'DISPOSABLE_SECRET_CANARY' not in result['text']
    assert 'Private visible text' not in json.dumps(store.events(mid))
    assert 'Private visible text' not in store.db.execute('SELECT result FROM gui_actions').fetchone()[0]
    gui.images[rid] = (0, result)
    assert gui.result(mid, {"session": "runtime-session", "id": rid})["result"]["text_available"] is False


def test_multiwindow_receipts_are_bounded_unique_and_text_is_utf8_bounded():
    windows = [{"window": key(), "width": 800, "height": 600} for _ in range(4)]
    assert receipt('state', {"windows": windows})['windows'] == windows
    for invalid in (windows + [dict(windows[0])], [windows[0], windows[0]]):
        with pytest.raises(ValueError):
            receipt('state', {"windows": invalid})
    for text in ('x' * 8193, 'é' * 4097):
        with pytest.raises(ValueError):
            receipt('read', {"window": key(), "text": text, "truncated": False})
