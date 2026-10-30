"""Prepared authenticated pre-ACK HTTP/PubSub custody; no public listener yet."""
import asyncio
import hashlib
import time

from .gateway import Conflict,digest
from .gateway_google_chat import credentials
from .gateway_google_chat_admission import Refused


class Receiver:
    def __init__(self,connector,value,originals,policy,current,*,http_verifier=None):
        self.connector=connector;self.value=credentials(value);self.originals=originals;self.policy=policy;self.current=current
        self.http_verifier=http_verifier;current()
        self.originals.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_source_refusals(
            id TEXT PRIMARY KEY,raw_sha256 TEXT NOT NULL,reason TEXT NOT NULL,
            first_seen REAL NOT NULL,last_seen REAL NOT NULL,repeats INTEGER NOT NULL)''')

    def _retain(self,raw):
        self.current();policy=self.policy()
        return self.originals.retain(policy,self.connector,self.value,raw,self.current)

    def http(self,headers,raw):
        self.current()
        if self.value['inbound']['mode']!='http' or self.http_verifier is None:raise PermissionError('saved private HTTP transport required')
        self.http_verifier.verify(headers)
        key=self._http_retain(raw);self.current()
        # Listener may return success only after this method completes. The
        # original is already durable even if dispatch or the response fails.
        return key

    def _http_retain(self,raw):
        try:return self._retain(raw)
        except Refused as error:
            self._refuse(raw,error.reason);self.current();return None

    async def http_async(self,headers,raw):
        self.current()
        if self.value['inbound']['mode']!='http' or self.http_verifier is None:raise PermissionError('saved private HTTP transport required')
        await asyncio.to_thread(self.http_verifier.verify,headers)
        # Keep every SQLite access on its owning asyncio thread.
        self.current();return self._http_retain(raw)

    def _refuse(self,raw,reason):
        if reason not in {'unapproved-route','self-or-automated','unsupported-event','ambiguous-space','unsupported-thread',
                'unsupported-content','pre-grant','unsupported-space','mention-required','unapproved-media'}:
            raise ValueError('finite Google Chat source refusal required')
        checksum=hashlib.sha256(raw).hexdigest();key=digest([self.connector,self.value,checksum,reason]);db=self.originals.db
        db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute('SELECT * FROM google_chat_source_refusals WHERE id=?',(key,)).fetchone();now=time.time()
            if row is None:
                if db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]>=4096:
                    raise Conflict('Google Chat refusal audit capacity reached; no transport acknowledgment')
                db.execute('INSERT INTO google_chat_source_refusals VALUES(?,?,?,?,?,?)',(key,checksum,reason,now,now,0))
            else:db.execute('UPDATE google_chat_source_refusals SET last_seen=?,repeats=MIN(repeats+1,2147483647) WHERE id=?',(now,key))
            self.current();db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def pubsub(self,message):
        self.current()
        if self.value['inbound']['mode']!='pubsub':raise PermissionError('saved private Pub/Sub transport required')
        # Called only by the dedicated authenticated SubscriberClient. The
        # native SDK message's ack action is observable in the process probe.
        from google.cloud.pubsub_v1.subscriber.message import Message
        if not isinstance(message,Message):raise TypeError('actual Google Pub/Sub SDK message required')
        try:
            raw=message.data
            try:key=self._retain(raw)
            except Refused as error:
                self._refuse(raw,error.reason);self.current();message.ack();return None
            self.current();message.ack();return key
        except BaseException:
            message.nack();raise
