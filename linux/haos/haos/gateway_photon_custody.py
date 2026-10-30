"""Two-stage FULL Photon custody, before SDK mapping and before NDJSON dispatch.

This private store is not an authenticated listener or a public profile factory.
The caller must provide current root-published authority and peer credentials.
"""
import base64
import hashlib
import json
import time

from .gateway import Conflict, digest
from .gateway_raw import NativeInbox
from .gateway_dingtalk_admission import parse, finite
from .gateway_line_ingress import _object
from .gateway_photon import checked_policy, credentials, scope
from .gateway_photon_admission import approve, timestamp, MAX_TOTAL

LIMIT = 96 * 1024 * 1024
MAX_NORMALIZED = 24 * 1024 * 1024


def normalized(raw, original, proof, value):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_NORMALIZED:
        raise Conflict('bounded Photon normalized source required')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=finite)
        message = original['event']['message']; envelope = proof['envelope']
        if (not isinstance(data, dict) or set(data) != {'messageId', 'platform', 'space', 'sender', 'content', 'timestamp'}
                or data['messageId'] != envelope['message_id'] or data['platform'] != 'iMessage'
                or data['sender'] != {'id': envelope['sender']} or not isinstance(data['space'], dict)
                or data['space'] != {'id': envelope['chat'], 'type': 'group' if ';+;' in envelope['chat'] else 'dm', 'phone': value['phone']}
                or timestamp(data['timestamp']) != timestamp(original['event']['occurredAt'])):
            raise ValueError
        pending = [(data['content'], 0)]; parts = {}; texts = []; total = 0; nodes = 0
        expected = {item['guid']: item for item in message['content']['attachments']}
        while pending:
            content, depth = pending.pop(0); nodes += 1
            if not isinstance(content, dict) or depth > 4 or nodes > 64:
                raise ValueError
            kind = content.get('type')
            if kind == 'reply':
                if depth != 0 or set(content) != {'type', 'targetMessageId', 'content'} or content['targetMessageId'] != (message.get('replyTargetGuid') or message.get('threadOriginatorGuid')):
                    raise ValueError
                pending.insert(0, (content['content'], depth + 1))
            elif kind == 'group':
                if set(content) != {'type', 'items'} or not isinstance(content['items'], list) or not 1 <= len(content['items']) <= 33:
                    raise ValueError
                children = []
                for item in content['items']:
                    if not isinstance(item, dict) or set(item) != {'id', 'content'}:
                        raise ValueError
                    children.append((item['content'], depth + 1))
                pending[0:0] = children
            elif kind == 'text':
                if set(content) != {'type', 'text'} or not isinstance(content['text'], str) or len(content['text'].encode()) > 65536:
                    raise ValueError
                texts.append(content['text'])
            elif kind in {'attachment', 'voice'}:
                if not {'type', 'id', 'name', 'mimeType', 'size', 'data', 'encoding'} <= set(content) <= {'type', 'id', 'name', 'mimeType', 'size', 'data', 'encoding', 'duration'}:
                    raise ValueError
                aid = content['id']; item = expected.get(aid)
                if (item is None or aid in parts or content['name'] != item['fileName'] or content['mimeType'] != item['mimeType']
                        or type(content['size']) is not int or content['size'] != item['totalBytes'] or content['encoding'] != 'base64'
                        or not isinstance(content['data'], str) or len(content['data']) > (item['totalBytes'] + 2) // 3 * 4):
                    raise ValueError
                binary = base64.b64decode(content['data'], validate=True)
                if len(binary) != item['totalBytes'] or base64.b64encode(binary).decode() != content['data']:
                    raise ValueError
                if kind == 'voice' and message.get('isAudioMessage') is not True:
                    raise ValueError
                total += len(binary)
                if total > MAX_TOTAL:
                    raise ValueError
                parts[aid] = {'sha256': hashlib.sha256(binary).hexdigest(), 'size': len(binary), 'mime': item['mimeType']}
            else:
                raise ValueError
        if (set(parts) != set(expected) or ''.join(texts) != message['content']['text'].replace('\ufffc', '')
                or (message.get('replyTargetGuid') or message.get('threadOriginatorGuid')) and data['content'].get('type') != 'reply'):
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError, OverflowError):
        raise Conflict('Photon native projection differs from independently retained source') from None
    return data, parts


class Originals:
    def __init__(self, path, redactor, current):
        if not callable(current):
            raise PermissionError('fresh Photon owner publication required')
        current(); self.current = current
        self.store = NativeInbox(path, redactor); self.db = self.store.db
        self.db.execute('PRAGMA max_page_count=' + str(LIMIT // self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_originals(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,account_scope TEXT NOT NULL,message_id TEXT NOT NULL,
            credential_scope TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            semantic_sha256 TEXT NOT NULL,raw BLOB NOT NULL,raw_sha256 TEXT NOT NULL,proof TEXT NOT NULL,
            normalized BLOB NOT NULL,normalized_sha256 TEXT NOT NULL,parts TEXT NOT NULL,
            admitted_receipt TEXT NOT NULL,created_at REAL NOT NULL)''')

    def close(self):
        self.store.close()

    def retain(self, policy, connector, value, raw):
        self.current(); proof = approve(policy, connector, value, raw); data = parse(raw)
        envelope = proof['envelope']; key = digest([connector, envelope['scope'], envelope['message_id']])
        semantic = digest([data['phone'], data['event']['message'], envelope['chat']])
        encoded = json.dumps(proof, sort_keys=True, separators=(',', ':'))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM photon_originals WHERE id=?', (key,)).fetchone()
            if row is None:
                live, size, count = self.db.execute('SELECT SUM(CASE WHEN length(raw)>0 THEN 1 ELSE 0 END),COALESCE(SUM(length(raw)+length(normalized)+length(proof)),0),COUNT(*) FROM photon_originals').fetchone()
                if (live or 0) >= 128 or count >= 65536 or size + len(raw) + len(encoded.encode()) > LIMIT:
                    raise Conflict('private Photon source capacity reached; owner recovery required')
                self.db.execute('INSERT INTO photon_originals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key, connector, envelope['scope'], envelope['message_id'], proof['credential_scope'], proof['binding_id'],
                        proof['binding_digest'], semantic, raw, proof['raw_sha256'], encoded, b'', '', '{}', '', time.time()))
            else:
                self._verify(row)
                if any(row[k] != proof[k] for k in ['credential_scope', 'binding_id', 'binding_digest']) or row['semantic_sha256'] != semantic:
                    raise Conflict('Photon replay changed its original, credential epoch or owner grant')
            policy.current_binding(proof); self.current(); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return key

    def _verify(self, row):
        if not row['raw'] or hashlib.sha256(row['raw']).hexdigest() != row['raw_sha256']:
            raise Conflict('Photon original unavailable or damaged; no automatic restoration')
        data = parse(bytes(row['raw'])); proof = json.loads(row['proof'])
        if (proof['raw_sha256'] != row['raw_sha256'] or proof['envelope']['message_id'] != row['message_id']
                or proof['envelope']['scope'] != row['account_scope']
                or digest([data['phone'], data['event']['message'], proof['envelope']['chat']]) != row['semantic_sha256']
                or any(proof[k] != row[k] for k in ['credential_scope', 'binding_id', 'binding_digest'])):
            raise Conflict('Photon original proof differs from retained source')
        if row['normalized']:
            if hashlib.sha256(row['normalized']).hexdigest() != row['normalized_sha256']:
                raise Conflict('Photon normalized source is damaged')
        elif row['normalized_sha256'] or row['parts'] != '{}':
            raise Conflict('Photon normalized source is missing')

    def load(self, key, policy, connector, value):
        self.current(); checked_policy(policy); value = credentials(value)
        row = self.db.execute('SELECT * FROM photon_originals WHERE id=?', (key,)).fetchone()
        if row is None: raise KeyError('unknown Photon source')
        self._verify(row); raw = bytes(row['raw']); proof = approve(policy, connector, value, raw)
        if row['connector'] != connector or row['account_scope'] != scope(value) or json.loads(row['proof']) != proof:
            raise Conflict('Photon retained source authority changed')
        if row['normalized']:
            _, parts = normalized(bytes(row['normalized']), parse(raw), proof, value)
            if json.loads(row['parts']) != parts: raise Conflict('Photon attachment proofs changed')
        policy.current_binding(proof); self.current()
        return dict(row), proof

    def decode(self, key, policy, connector, value, raw):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row, proof = self.load(key, policy, connector, value)
            _, parts = normalized(raw, parse(bytes(row['raw'])), proof, value)
            sha = hashlib.sha256(raw).hexdigest()
            if row['normalized']:
                if sha != row['normalized_sha256']:
                    raise Conflict('Photon normalized replay changed after first custody')
            else:
                size = self.db.execute('SELECT COALESCE(SUM(length(raw)+length(normalized)+length(proof)),0) FROM photon_originals').fetchone()[0]
                if size + len(raw) > LIMIT: raise Conflict('private Photon normalized capacity reached')
                self.db.execute('UPDATE photon_originals SET normalized=?,normalized_sha256=?,parts=? WHERE id=?',
                    (raw, sha, json.dumps(parts, sort_keys=True, separators=(',', ':')), key))
            self.current(); policy.current_binding(proof); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise

    def admitted(self, key, receipt, policy, connector, value):
        if not isinstance(receipt, str) or not re_full_hash(receipt):
            raise ValueError('exact parent custody receipt required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row, proof = self.load(key, policy, connector, value)
            if not row['normalized']: raise Conflict('Photon native source has no durable decoded body')
            if row['admitted_receipt'] and row['admitted_receipt'] != receipt:
                raise Conflict('Photon source belongs to another parent custody receipt')
            self.db.execute('UPDATE photon_originals SET admitted_receipt=? WHERE id=?', (receipt, key))
            self.current(); policy.current_binding(proof); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise


def re_full_hash(value):
    return len(value) == 64 and all(c in '0123456789abcdef' for c in value)
