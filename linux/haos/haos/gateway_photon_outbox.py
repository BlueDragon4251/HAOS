"""Durable one-use write permission bound to a completed native Photon source."""
import hashlib
import hmac
import re
import secrets
import time

from .gateway import Conflict, digest
from .gateway_photon import message_id, scope, checked_policy

HASH = re.compile('[a-f0-9]{64}\\Z')


class Journal:
    def __init__(self, inbox, originals, connector, value, policy, current):
        self.inbox = inbox; self.db = inbox.db; self.originals = originals
        self.connector = connector; self.value = value; self.policy = policy; self.current = current
        current(); checked_policy(policy())
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_output_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,
            fingerprint TEXT NOT NULL,source_id TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            thread TEXT NOT NULL,wire_sha256 TEXT NOT NULL,capability_sha256 TEXT NOT NULL,
            expires_at REAL NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,
            PRIMARY KEY(delivery_id,attempt))''')
        # An old process cannot consume an old pending capability through a
        # new PID/token-bound control server. A consumed write stays uncertain.
        self.db.execute("UPDATE photon_output_intents SET state='not-dispatched' WHERE connector=? AND state='prepared'", (connector,))
        self.db.execute("UPDATE photon_output_intents SET state='uncertain' WHERE connector=? AND state='writing'", (connector,))

    def source(self, binding, source_id, thread):
        self.current(); policy = checked_policy(self.policy()); message_id(source_id)
        if binding != policy.current_binding({'binding_id': binding['id'], 'binding_digest': digest(binding)}):
            raise PermissionError('unchanged Photon reply binding required')
        if binding['connector'] != self.connector or 'read' not in binding['capabilities']:
            raise PermissionError('exact current Photon read/reply grant required')
        if not isinstance(thread, str) or not (binding['thread'] == thread or binding.get('all_threads') is True):
            raise PermissionError('exact Photon reply thread required')
        if thread: message_id(thread)
        try:
            rows = self.db.execute('''SELECT p.*,n.state AS native_state,n.binding_id AS native_binding_id,
                n.binding_digest AS native_binding_digest,n.fingerprint AS native_fingerprint
                FROM photon_native_projection p JOIN native_inbox n ON p.source_key=n.id
                WHERE n.connector=? AND n.message_id=?''', (self.connector, source_id)).fetchall()
        except Exception:
            raise PermissionError('completed native Photon source projection required') from None
        if len(rows) != 1: raise PermissionError('one completed native Photon reply source required')
        row = rows[0]
        original, proof = self.originals.load(row['raw_id'], policy, self.connector, self.value)
        envelope = proof['envelope']
        native_key = self.inbox.key(self.connector, envelope)
        parent_key = digest([self.connector, *(envelope[k] for k in ['scope', 'chat', 'thread', 'message_id'])])
        if (row['native_state'] != 'committed' or row['native_binding_id'] != binding['id']
                or any(row[name] != digest(binding) for name in ['binding_digest', 'native_binding_digest'])
                or row['envelope_sha256'] != row['native_fingerprint'] or row['source_key'] != native_key
                or row['raw_sha256'] != original['raw_sha256'] or row['normalized_sha256'] != original['normalized_sha256']
                or row['credential_scope'] != proof['credential_scope'] or original['admitted_receipt'] != parent_key
                or envelope['message_id'] != source_id or envelope['thread'] != thread or envelope['scope'] != scope(self.value)
                or any(envelope[field] != binding[field] for field in ['sender', 'chat', 'scope'])):
            raise PermissionError('Photon reply source differs from completed independent source custody')
        return original, proof

    def prepare(self, binding, delivery_id, attempt, source_id, thread, content, wire_text, context_sha256):
        if (not isinstance(delivery_id, str) or not HASH.fullmatch(delivery_id)
                or type(attempt) is not int or not 1 <= attempt <= 5
                or not isinstance(context_sha256, str) or not HASH.fullmatch(context_sha256)
                or any(not isinstance(text, str) or not text.strip() or len(text) > 8000 or len(text.encode()) > 32000
                    or self.inbox.redactor.text(text) != text for text in [content, wire_text])):
            raise PermissionError('exact bounded private Photon outbox content and identity required')
        original, _ = self.source(binding, source_id, thread)
        wire = {'spaceId': binding['chat'], 'text': wire_text, 'format': 'text', 'replyTo': source_id}
        fingerprint = digest([self.connector, self.value, binding, original['id'], original['raw_sha256'],
            original['normalized_sha256'], thread, content, wire, context_sha256])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.source(binding, source_id, thread)
            previous = self.db.execute('SELECT * FROM photon_output_intents WHERE delivery_id=? ORDER BY attempt', (delivery_id,)).fetchall()
            for row in previous:
                if row['connector'] != self.connector or row['fingerprint'] != fingerprint:
                    raise Conflict('Photon delivery changed its first source, account, content or authority')
                if row['state'] == 'confirmed':
                    message_id(row['receipt']); self.db.execute('COMMIT'); return {'state': 'confirmed', 'receipt': row['receipt']}
                if row['state'] in {'writing', 'uncertain'}:
                    self.db.execute('COMMIT'); return {'state': 'uncertain'}
                if row['state'] not in {'prepared', 'not-dispatched'} or row['receipt']:
                    raise Conflict('damaged Photon output intent')
                if row['state'] == 'prepared': raise Conflict('Photon output capability is already outstanding')
            if (previous and (previous[-1]['attempt'] != attempt - 1 or previous[-1]['state'] != 'not-dispatched')
                    or not previous and attempt != 1):
                raise Conflict('sequential controller Photon outbox attempts required')
            if self.db.execute('SELECT COUNT(*) FROM photon_output_intents').fetchone()[0] >= 65536:
                raise Conflict('Photon output history full; inspected owner recovery required')
            token = secrets.token_hex(32)
            self.db.execute('INSERT INTO photon_output_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (delivery_id, attempt, self.connector, fingerprint, source_id, binding['id'], digest(binding), thread,
                    digest(wire), hashlib.sha256(token.encode()).hexdigest(), time.time() + 30, 'prepared', ''))
            self.current(); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return {'state': 'prepared', 'wire': {**wire, 'haosCapability': token}, 'delivery_id': delivery_id, 'attempt': attempt}

    def consume(self, body):
        self.current()
        if (not isinstance(body, dict) or set(body) != {'spaceId', 'text', 'format', 'replyTo', 'haosCapability'}
                or not isinstance(body['haosCapability'], str) or not HASH.fullmatch(body['haosCapability'])):
            raise PermissionError('one exact Photon native write capability required')
        token_sha = hashlib.sha256(body['haosCapability'].encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            rows = self.db.execute('SELECT * FROM photon_output_intents WHERE connector=? AND capability_sha256=?', (self.connector, token_sha)).fetchall()
            if len(rows) != 1: raise PermissionError('unknown Photon output capability')
            row = rows[0]
            wire = {key: body[key] for key in ['spaceId', 'text', 'format', 'replyTo']}
            if (row['state'] != 'prepared' or row['expires_at'] <= time.time() or not hmac.compare_digest(row['wire_sha256'], digest(wire))):
                raise PermissionError('Photon output capability expired, consumed or changed')
            binding = self.policy().current_binding(dict(row))
            self.source(binding, row['source_id'], row['thread'])
            changed = self.db.execute("UPDATE photon_output_intents SET state='writing' WHERE delivery_id=? AND attempt=? AND state='prepared'",
                (row['delivery_id'], row['attempt'])).rowcount
            if changed != 1: raise Conflict('Photon output capability changed during consumption')
            self.current(); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return {'approved': True}

    def result(self, delivery_id, attempt, receipt=None):
        # Revocation cannot erase evidence that a write may have happened.
        if receipt is not None: self.current(); message_id(receipt)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM photon_output_intents WHERE delivery_id=? AND attempt=? AND connector=?',
                (delivery_id, attempt, self.connector)).fetchone()
            if row is None: raise Conflict('unknown Photon output result')
            if receipt is not None:
                if row['state'] == 'confirmed' and row['receipt'] == receipt: self.db.execute('COMMIT'); return 'confirmed'
                if row['state'] != 'writing': raise Conflict('Photon acceptance lacks a consumed native write')
                self.source(self.policy().current_binding(dict(row)), row['source_id'], row['thread'])
                state = 'confirmed'
            elif row['state'] == 'prepared': state = 'not-dispatched'
            elif row['state'] in {'writing', 'uncertain'}: state = 'uncertain'
            elif row['state'] == 'confirmed': state = 'confirmed'; receipt = row['receipt']
            else: state = row['state']
            self.db.execute('UPDATE photon_output_intents SET state=?,receipt=? WHERE delivery_id=? AND attempt=?',
                (state, receipt or '', delivery_id, attempt))
            if receipt is not None: self.current()
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return state
