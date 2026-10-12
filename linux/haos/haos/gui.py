"""Durable, mission-scoped requests for the native isolated browser capability.

No commands, host window IDs, file paths, URLs, clipboard or compositor sockets
cross this boundary. Dispatch is committed before native execution, never replayed.
"""
import base64
import asyncio
import hashlib
import json
import re
import time
import uuid

from .store import Conflict
from .application_protocol import OPERATIONS as APPLICATION_OPERATIONS,action as application_action,receipt as application_receipt
from .theme_protocol import OPERATIONS as THEME_OPERATIONS,action as theme_action,receipt as theme_receipt

OPERATIONS = {"open", "state", "focus", "close", "click", "scroll", "type", "key", "capture", "inspect", "read", "locate", "center", "workspace"} | APPLICATION_OPERATIONS | THEME_OPERATIONS
WINDOW_LIMIT = 4
KEYS = {"Tab", "Enter", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "Escape"}


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("a canonical UUID is required")
    return value


def action(data):
    if isinstance(data,dict) and data.get('operation') in THEME_OPERATIONS:return theme_action(data)
    if isinstance(data,dict) and data.get('operation') in APPLICATION_OPERATIONS:
        return application_action(data)
    if not isinstance(data, dict) or data.get("operation") not in OPERATIONS:
        raise PermissionError("GUI capability denied")
    op = data["operation"]
    fields = {"operation"}
    if op == "open":
        fields.add("html")
        if not isinstance(data.get("html"), str) or not 1 <= len(data["html"].encode()) <= 32768:
            raise ValueError("local browser document must contain 1–32768 bytes")
        if re.search(r"<\s*(?:iframe|frame|frameset|object|embed|applet)\b", data["html"], re.I):
            raise PermissionError("nested application surfaces are not authorized")
    elif op != "state":
        fields.add("window")
        identifier(data.get("window"))
    if op in {"click", "scroll"}:
        fields.update({"x", "y"})
        if any(type(data.get(k)) is not int for k in ("x", "y")) or not 0 <= data["x"] < 800 or not 48 <= data["y"] < 600:
            raise ValueError("click must target the mission document")
    if op == "scroll":
        fields.update({"deltaX", "deltaY"})
        if (any(type(data.get(k)) is not int or abs(data[k]) > 552 for k in ("deltaX", "deltaY"))
                or data["deltaX"] == data["deltaY"] == 0):
            raise ValueError("scroll must contain bounded nonzero document offsets")
    if op == "type":
        fields.add("text")
        if not isinstance(data.get("text"), str) or not 1 <= len(data["text"].encode()) <= 4096 or any(ord(c) < 32 for c in data["text"]):
            raise ValueError("type accepts bounded plain text without control characters")
    if op == "key":
        fields.add("key")
        if data.get("key") not in KEYS:
            raise PermissionError("global shortcuts and clipboard keys are denied")
    if op == "workspace":
        fields.add("workspace")
        if type(data.get("workspace")) is not int or not 1 <= data["workspace"] <= 8:
            raise PermissionError("mission workspace denied")
    if set(data) != fields:
        raise PermissionError("unexpected GUI capability parameters")
    return dict(data)


def receipt(op, data):
    """Native replies are bounded too; captures never become durable ledger data."""
    if op in APPLICATION_OPERATIONS:return application_receipt(op,data)
    if op in THEME_OPERATIONS:return theme_receipt(op,data)
    if not isinstance(data, dict):
        raise ValueError("invalid GUI receipt")
    fields = {"window", "width", "height"}
    if op == "locate":
        if (set(data) != {"window", "width", "height", "focused", "workspace"}
                or type(data["focused"]) is not bool
                or data["workspace"] is not None and (type(data["workspace"]) is not int or not 1 <= data["workspace"] <= 255)
                or any(type(data[k]) is not int or not 1 <= data[k] <= 16384 for k in ("width", "height"))):
            raise ValueError("invalid mission compositor state")
        identifier(data["window"])
        return data
    if op == "read":
        if (set(data) != {"window", "text", "truncated"} or not isinstance(data["text"], str)
                or len(data["text"].encode()) > 8192 or type(data["truncated"]) is not bool):
            raise ValueError("invalid visible document text")
        identifier(data["window"])
        return data
    if op == "inspect":
        if set(data) != {"window", "fields"} or not isinstance(data["fields"], list) or len(data["fields"]) > 32:
            raise ValueError("invalid document inspection")
        identifier(data["window"])
        indices = set()
        for field in data["fields"]:
            if (not isinstance(field, dict) or set(field) != {"index", "name", "type", "value", "truncated", "sensitive"}
                    or type(field["index"]) is not int or not 0 <= field["index"] < 65536 or field["index"] in indices
                    or field["type"] not in {"text", "number", "checkbox", "password", "file", "textarea", "email", "url", "other"}
                    or type(field["truncated"]) is not bool or type(field["sensitive"]) is not bool
                    or not isinstance(field["name"], str) or len(field["name"]) > 128
                    or not isinstance(field["value"], str) or len(field["value"]) > 512):
                raise ValueError("invalid document field")
            indices.add(field["index"])
            if field["sensitive"] != (field["type"] in {"password", "file"}) or field["sensitive"] and field["value"] != "[redacted]":
                raise PermissionError("sensitive document field denied")
        if len(json.dumps(data).encode()) > 16384:
            raise ValueError("document inspection exceeds its limit")
        return data
    if op == "state":
        if set(data) != {"windows"} or not isinstance(data["windows"], list) or len(data["windows"]) > WINDOW_LIMIT:
            raise ValueError("invalid window inventory")
        identifiers = set()
        for win in data["windows"]:
            receipt("open", win)
            if win["window"] in identifiers:
                raise ValueError("duplicate window identity")
            identifiers.add(win["window"])
        return data
    if op in {"open", "capture"}:
        if op == "capture":
            fields.add("jpeg")
        if set(data) != fields or any(type(data.get(k)) is not int for k in ("width", "height")):
            raise ValueError("invalid browser dimensions")
        identifier(data["window"])
        if data["width"] != 800 or data["height"] != 600:
            raise ValueError("browser dimensions changed")
        if op == "capture":
            if not isinstance(data["jpeg"], str) or len(data["jpeg"]) > 98304:
                raise ValueError("capture exceeds its limit")
            image = base64.b64decode(data["jpeg"], validate=True)
            if not 100 < len(image) <= 73728 or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
                raise ValueError("invalid JPEG receipt")
    elif set(data) != {"window"}:
        raise ValueError("invalid GUI action receipt")
    else:
        identifier(data["window"])
    return data


class GuiBroker:
    def __init__(self, store):
        self.store = store
        self.epoch = None
        self.seen_at = 0
        self.application_seen_at=0
        self.application_epoch=str(uuid.uuid4())
        self.images = {}  # short-lived replies only, never screenshots in SQLite
        store.db.execute("""CREATE TABLE IF NOT EXISTS gui_actions (
            id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
            request_hash TEXT NOT NULL, operation TEXT NOT NULL, arguments TEXT,
            state TEXT NOT NULL, created_at REAL NOT NULL, epoch TEXT, result TEXT)""")
        self.invalidate("controller restarted")

    def invalidate(self, reason, *, native_only=False):
        with self.store.transaction():
            for row in self.store.db.execute("SELECT id,mission_id,operation FROM gui_actions WHERE state IN ('pending','dispatched')").fetchall():
                if native_only and row['operation'] in APPLICATION_OPERATIONS:continue
                self.store.db.execute("UPDATE gui_actions SET state='uncertain',arguments=NULL,result=? WHERE id=?",
                                      (json.dumps({"error": reason}), row["id"]))
                self.store._event(row["mission_id"], "gui.uncertain", {"id": row["id"]})
        if native_only:
            application_ids={row[0] for row in self.store.db.execute("SELECT id FROM gui_actions WHERE operation LIKE 'app.%'")}
            self.images={k:v for k,v in self.images.items() if k in application_ids}
        else:self.images.clear()

    def authorize(self, current, session):
        if not current:
            raise PermissionError("no active GUI mission")
        row = self.store.get(current)
        if (row["state"] != "running" or row["phase"] != "dispatching" or row["cancel_requested"]
                or row["deadline"] <= time.time() or session not in {row["session_id"], row["stored_session_id"]} or not session):
            raise PermissionError("GUI session is not the running mission")
        return row

    def submit(self, current, params):
        if set(params) != {"session", "id", "action"}:
            raise ValueError("invalid GUI admission")
        row = self.authorize(current, params["session"])
        key, args = identifier(params["id"]), action(params["action"])
        encoded = json.dumps(args, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.transaction():
            old = self.store.db.execute("SELECT * FROM gui_actions WHERE id=?", (key,)).fetchone()
            if old:
                if old["mission_id"] != row["id"] or old["request_hash"] != digest:
                    raise Conflict("GUI request ID already used")
                return self.result(current, {"session": params["session"], "id": key})
            if args['operation'] in APPLICATION_OPERATIONS:
                if time.time()-self.application_seen_at>3:raise Conflict('independent application authority is unavailable')
            elif not self.epoch or time.time() - self.seen_at > 3:
                raise Conflict("native GUI broker is unavailable")
            count = self.store.db.execute("SELECT COUNT(*) FROM gui_actions WHERE mission_id=?", (row["id"],)).fetchone()[0]
            recent = self.store.db.execute("SELECT COUNT(*) FROM gui_actions WHERE created_at>?", (time.time() - 60,)).fetchone()[0]
            if count >= 1024 or recent >= 120:
                raise Conflict("GUI action budget exhausted")
            # Documents/input may contain personal data. Keep them only until dispatch/ack,
            # redacting known secrets before transfer. Audit stores only their digest.
            safe = self.store.redactor.clean(args)
            self.store.db.execute("INSERT INTO gui_actions VALUES(?,?,?,?,?,'pending',?,NULL,NULL)",
                                  (key, row["id"], digest, args["operation"], json.dumps(safe), time.time()))
            self.store._event(row["id"], "gui.admitted", {"id": key, "operation": args["operation"], "sha256": digest})
        return {"id": key, "state": "pending", "result": None}

    def result(self, current, params):
        if set(params) != {"session", "id"}:
            raise ValueError("invalid GUI result lookup")
        mission = self.authorize(current, params["session"])
        row = self.store.db.execute("SELECT * FROM gui_actions WHERE id=? AND mission_id=?", (identifier(params["id"]), mission["id"])).fetchone()
        if not row:
            raise KeyError("unknown GUI action")
        self.prune_images()
        data = json.loads(row["result"]) if row["result"] else None
        if row["id"] in self.images:
            data = self.images[row["id"]][1]
        return {"id": row["id"], "state": row["state"], "result": data}

    def prune_images(self):
        self.images = {key: value for key, value in self.images.items() if time.time() - value[0] < 15}

    def attach(self, params):
        if set(params) != {"epoch"}:
            raise ValueError("invalid GUI attachment")
        epoch = identifier(params["epoch"])
        if epoch != self.epoch:
            self.invalidate("native GUI session replaced; inspect before retrying",native_only=True)
        self.epoch, self.seen_at = epoch, time.time()
        return {"attached": True}

    def poll(self, current, params):
        if set(params) != {"epoch"} or params["epoch"] != self.epoch:
            raise PermissionError("stale GUI session")
        self.seen_at = time.time()
        self.prune_images()
        active = None
        if current:
            row = self.store.get(current)
            if row["state"] == "running" and not row["cancel_requested"] and row["deadline"] > time.time():
                active = current
        with self.store.transaction():
            stale = self.store.db.execute("SELECT id,mission_id FROM gui_actions WHERE operation NOT LIKE 'app.%' AND state IN ('pending','dispatched') AND (mission_id!=? OR created_at<?)",
                                          (active or "", time.time() - 20)).fetchall()
            for row in stale:
                self.store.db.execute("UPDATE gui_actions SET state='uncertain',arguments=NULL,result=? WHERE id=?", ('{"error":"GUI action expired or mission ended"}', row["id"]))
                self.store._event(row["mission_id"], "gui.uncertain", {"id": row["id"]})
            row = self.store.db.execute("SELECT * FROM gui_actions WHERE operation NOT LIKE 'app.%' AND state='pending' AND mission_id=? ORDER BY created_at LIMIT 1", (active,)).fetchone()
            request = None
            if row:
                request = {"id": row["id"], "mission": active, "action": json.loads(row["arguments"])}
                self.store.db.execute("UPDATE gui_actions SET state='dispatched',epoch=?,arguments=NULL WHERE id=?", (self.epoch, row["id"]))
                self.store._event(active, "gui.dispatched", {"id": row["id"], "operation": row["operation"]})
        return {"mission": active, "request": request}

    def acknowledge(self, params):
        if set(params) != {"epoch", "id", "ok", "result"} or params["epoch"] != self.epoch or type(params["ok"]) is not bool:
            raise PermissionError("invalid GUI acknowledgement")
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM gui_actions WHERE id=?", (identifier(params["id"]),)).fetchone()
            if not row or row["operation"] in APPLICATION_OPERATIONS or row["state"] != "dispatched" or row["epoch"] != self.epoch:
                raise Conflict("GUI action no longer awaits a receipt")
            data = receipt(row["operation"], params["result"]) if params["ok"] else {"error": "native GUI action failed"}
            if row['operation']=='theme.stage' and params['ok'] and data['name']!='haos-t-'+row['mission_id'].replace('-',''):
                raise PermissionError('theme revision belongs to another mission')
            if row["operation"] == "capture" and params["ok"]:
                self.prune_images()
                self.images[row["id"]] = (time.time(), data)
                try:
                    asyncio.get_running_loop().call_later(15, self.images.pop, row["id"], None)
                except RuntimeError:
                    pass  # synchronous offline tests use the same expiry check on lookup
                image = base64.b64decode(data["jpeg"])
                data = {"window": data["window"], "width": 800, "height": 600, "sha256": hashlib.sha256(image).hexdigest(),
                        "bytes": len(image), "capture_available": False}
            elif row["operation"] in {"inspect", "read"} and params["ok"]:
                self.prune_images()
                self.images[row["id"]] = (time.time(), self.store.redactor.clean(data))
                try:
                    asyncio.get_running_loop().call_later(15, self.images.pop, row["id"], None)
                except RuntimeError:
                    pass
                encoded = json.dumps(data, sort_keys=True).encode()
                metadata = {"field_count": len(data["fields"]), "inspection_available": False} if row["operation"] == "inspect" else {"text_available": False}
                data = {"window": data["window"], "sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded), **metadata}
            state = "succeeded" if params["ok"] else "failed"
            self.store.db.execute("UPDATE gui_actions SET state=?,result=? WHERE id=?", (state, json.dumps(data), row["id"]))
            self.store._event(row["mission_id"], "gui." + state, {"id": row["id"], "operation": row["operation"],
                                                             **({"sha256": data["sha256"], "bytes": data["bytes"]} if "sha256" in data else {})})
        return {"accepted": True}

    def application_poll(self,current,*,dispatch=True):
        self.prune_images()
        active=None
        if current:
            row=self.store.get(current)
            try:self.authorize(current,row['session_id']);active=current
            except PermissionError:pass
        with self.store.transaction():
            for row in self.store.db.execute("SELECT id,mission_id FROM gui_actions WHERE operation LIKE 'app.%' AND state IN ('pending','dispatched') AND (mission_id!=? OR created_at<?)",
                    (active or '',time.time()-20)).fetchall():
                self.store.db.execute("UPDATE gui_actions SET state='uncertain',arguments=NULL,result=? WHERE id=?",('{"error":"application action expired or mission ended"}',row['id']))
                self.store._event(row['mission_id'],'gui.uncertain',{'id':row['id']})
            if not dispatch:return None
            row=self.store.db.execute("SELECT * FROM gui_actions WHERE operation LIKE 'app.%' AND state='pending' AND mission_id=? ORDER BY created_at LIMIT 1",(active,)).fetchone()
            if not row:return None
            result={'id':row['id'],'mission':active,'action':json.loads(row['arguments'])}
            self.store.db.execute("UPDATE gui_actions SET state='dispatched',epoch=?,arguments=NULL WHERE id=?",(self.application_epoch,row['id']))
            self.store._event(active,'gui.dispatched',{'id':row['id'],'operation':row['operation']})
            return result

    def application_acknowledge(self,key,*,result=None):
        """Internal root-worker receipt; never callable through Herald gui.ack."""
        with self.store.transaction():
            row=self.store.db.execute('SELECT * FROM gui_actions WHERE id=?',(identifier(key),)).fetchone()
            if not row or row['operation'] not in APPLICATION_OPERATIONS or row['state']!='dispatched' or row['epoch']!=self.application_epoch:
                raise Conflict('application no longer awaits an independent receipt')
            if result is None:
                # The root authority may have performed input before losing the
                # response. Keep this action uncertain and permanently consumed.
                state='uncertain';data={'error':'application receipt unavailable; reconcile before retrying'}
            else:
                data=receipt(row['operation'],result);state='succeeded'
                if row['operation']=='app.start' and data['instance']!=key:
                    raise PermissionError('application instance does not match the admitted launch')
                if row['operation']=='app.capture':
                    self.prune_images();self.images[key]=(time.time(),data)
                    try:asyncio.get_running_loop().call_later(15,self.images.pop,key,None)
                    except RuntimeError:pass
                    data={k:v for k,v in data.items() if k not in {'mime','base64'}} | {'capture_available':False}
            self.store.db.execute('UPDATE gui_actions SET state=?,result=? WHERE id=?',(state,json.dumps(data),key))
            self.store._event(row['mission_id'],'gui.'+state,{'id':key,'operation':row['operation'],
                **({k:data[k] for k in ('sha256','bytes')} if 'sha256' in data else {})})
        return {'accepted':True}

    def application_snapshot(self,mission):
        """Read-only actual receipts/ephemeral frames, no commands or new captures."""
        identifier(mission);current=self.store.get(mission);self.prune_images()
        now=time.time()
        active=(current['state']=='running' and current['phase']=='dispatching'
                and not current['cancel_requested'] and current['deadline']>now)
        rows=self.store.db.execute("SELECT id,operation,result,created_at FROM gui_actions WHERE mission_id=? AND state='succeeded' AND operation LIKE 'app.%' ORDER BY created_at,id",(mission,)).fetchall()
        applications={}
        for row in rows:
            data=json.loads(row['result'])
            if row['operation']=='app.start':
                receipt(row['operation'],data)
                if data['instance']!=row['id']:raise PermissionError('application inventory launch identity mismatch')
                applications[data['instance']]={'instance':data['instance'],'program':data['program'],
                    'admitted_at':row['created_at'],'observed_at':None,'running':None,'windows':None,
                    'capture_at':None,'capture_sha256':None,'jpeg':None}
            elif data.get('instance') in applications:
                item=applications[data['instance']]
                if row['operation']=='app.state':
                    receipt(row['operation'],data)
                    item.update(observed_at=row['created_at'],running=data['running'],windows=data['windows'])
                elif row['operation']=='app.close':
                    receipt(row['operation'],data);applications.pop(data['instance'])
                elif row['operation']=='app.capture' and active and row['id'] in self.images:
                    at,frame=self.images[row['id']];receipt('app.capture',frame)
                    if frame['instance']!=data['instance']:raise PermissionError('application capture identity mismatch')
                    item.update(capture_at=at,capture_sha256=frame['sha256'],jpeg=frame['base64'])
        return {'mission':mission,'snapshot_at':now,'mission_active':bool(active),
                'authority_available':0<=now-self.application_seen_at<3,
                'applications':list(applications.values())[-4:]}
