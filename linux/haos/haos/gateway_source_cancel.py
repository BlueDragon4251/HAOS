"""Atomic root cancellation against an original source, including before admission.

A tombstone precedes any later source admission. A missing mission is proved by
this root transaction, never inferred from the gateway's possibly stale queue.
"""
import time

from .store import Conflict


class SourceCancellation:
    def __init__(self,store):
        self.store=store;self.db=store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS gateway_source_cancellations(
            source_key TEXT PRIMARY KEY,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            identity TEXT NOT NULL,envelope_sha256 TEXT NOT NULL,mission_id TEXT NOT NULL,sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')

    def checked(self,row):
        from .gateway import digest
        fields=['source_key','connector','binding_id','binding_digest','identity','envelope_sha256','mission_id']
        if row['sha256']!=digest([row[key] for key in fields]):raise Conflict('root source cancellation proof changed')
        return row

    def before_admission(self,key):
        row=self.db.execute('SELECT * FROM gateway_source_cancellations WHERE source_key=?',(key,)).fetchone()
        if row is not None:
            self.checked(row)
            if not row['mission_id']:raise Conflict('source cancelled by root before mission admission')

    def cancel(self,policy,params):
        from .gateway import digest
        if not isinstance(params,dict) or set(params)!={'connector','envelope','binding'}:
            raise ValueError('exact original source and owner cancellation epoch required')
        connector=params['connector'];envelope=params['envelope'];binding=policy.authorize(connector,envelope)
        if (policy.connectors[connector]['platform']!='a2a' or not {'cancel','read'}<=set(binding['capabilities'])
                or params['binding']!={'binding_id':binding['id'],'binding_digest':digest(binding)}):
            raise PermissionError('independent exact A2A source cancellation/read grant required')
        key=digest([connector,envelope['scope'],envelope['chat'],envelope['thread'],envelope['message_id']])
        base=[key,connector,binding['id'],digest(binding),binding['identity'],digest(envelope)]
        with self.store.transaction():
            prior=self.db.execute('SELECT * FROM gateway_source_cancellations WHERE source_key=?',(key,)).fetchone()
            if prior is not None:
                self.checked(prior)
                if [prior[k] for k in ['source_key','connector','binding_id','binding_digest','identity','envelope_sha256']]!=base:
                    raise Conflict('source cancellation replay changed source, grant or identity')
                mid=prior['mission_id']
            else:
                admitted=self.db.execute('SELECT * FROM gateway_inbox WHERE key=?',(key,)).fetchone();mid=''
                if admitted is not None:
                    if (admitted['binding_id']!=binding['id'] or admitted['binding_digest']!=digest(binding)
                            or admitted['identity']!=binding['identity']):raise PermissionError('source mission belongs to another grant')
                    mid=admitted['mission_id'];mission=self.store.get(mid)
                    if mission['actor']!='gateway:'+binding['identity']:raise PermissionError('source mission belongs to another identity')
                    self.store.request_cancel(mid,mission['actor'])
                if self.db.execute('SELECT COUNT(*) FROM gateway_source_cancellations').fetchone()[0]>=65536:
                    raise Conflict('root source cancellation history full; owner recovery required')
                values=[*base,mid]
                self.db.execute('INSERT INTO gateway_source_cancellations VALUES(?,?,?,?,?,?,?,?,?)',(*values,digest(values),time.time()))
            from .gateway_raw import NativeInbox
            return {'source_key':NativeInbox.key(connector,envelope),'prevented':not bool(mid),'mission_id':mid or None}
