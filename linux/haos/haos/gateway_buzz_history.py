"""Bounded FULL-journal catch-up; custody always precedes composite cursor commit."""
import asyncio
import json
import time

from .gateway import Conflict,digest
from .gateway_buzz import HEX,scope
from .gateway_raw import NativeInbox


class History:
    def __init__(self,path,reader,redactor,capture):
        if not callable(capture):raise PermissionError('durable Buzz original capture required')
        reader.peers();self.reader=reader;self.capture=capture;self.locks={}
        self.store=NativeInbox(path,redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(64*1024*1024//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS buzz_history(
            channel TEXT PRIMARY KEY,pin TEXT NOT NULL,floor_ts INTEGER NOT NULL,
            ceiling_ts INTEGER NOT NULL,before_ts INTEGER NOT NULL,before_id TEXT NOT NULL,
            revision INTEGER NOT NULL,complete INTEGER NOT NULL,page TEXT NOT NULL)''')

    def close(self):self.store.close()

    def grant(self,channel):
        reader=self.reader;reader.peers();policy=reader.current()
        if channel not in reader.value['channels']:raise PermissionError('owner-selected Buzz history channel required')
        rows=[row for row in policy.bindings.values() if row['connector']==reader.connector
            and row['scope']==scope(reader.value) and row['chat']==channel]
        if not rows:raise PermissionError('independent current Buzz history grants required')
        rows.sort(key=lambda row:row['id'])
        return digest([reader.connector,reader.value,rows]),min((row['since']+999)//1000 for row in rows)

    def validate(self,row,pin,earliest):
        if (row['pin']!=pin or any(type(row[key]) is not int or not 0<row[key]<2**53 for key in ['floor_ts','ceiling_ts','before_ts'])
                or not earliest<=row['floor_ts']<=row['before_ts']<=row['ceiling_ts']
                or type(row['revision']) is not int or not 0<=row['revision']<2**53 or row['complete'] not in {0,1}
                or not isinstance(row['before_id'],str) or row['before_id'] and not HEX.fullmatch(row['before_id'])
                or not isinstance(row['page'],str) or len(row['page'].encode())>16384):
            raise Conflict('retained Buzz history cursor differs from current account grant or finite bounds')
        return dict(row)

    async def step(self,channel):
        # A sweep is bounded to one actual CLI page per call. Reopen resumes the
        # exact saved upper tuple; it never seeds unseen history as already read.
        self.grant(channel)
        async with self.locks.setdefault(channel,asyncio.Lock()):
            pin,earliest=self.grant(channel)
            row=self.db.execute('SELECT * FROM buzz_history WHERE channel=?',(channel,)).fetchone()
            if row is None:
                now=max(earliest,int(time.time()))
                self.db.execute('INSERT INTO buzz_history VALUES(?,?,?,?,?,?,?,?,?)',(channel,pin,earliest,now,now,'',0,0,'[]'))
                row=self.db.execute('SELECT * FROM buzz_history WHERE channel=?',(channel,)).fetchone()
            state=self.validate(row,pin,earliest)
            if state['complete']:
                # Keep an inclusive five-minute overlap for the permitted signed
                # clock skew/late relay arrival. Durable event IDs absorb replay.
                floor=max(earliest,state['ceiling_ts']-300)
                ceiling=max(state['ceiling_ts'],int(time.time()))
                state.update(floor_ts=floor,ceiling_ts=ceiling,before_ts=ceiling,before_id='')
            args=['messages','get','--channel',channel,'--limit','50','--since',str(state['floor_ts']),'--before',str(state['before_ts'])]
            _,out,_=await self.reader.run(args,before_id=state['before_id'] or None)
            events=json.loads(out);results=[]
            for event in sorted(events,key=lambda item:(item['created_at'],item['id'])):
                self.grant(channel)
                accepted=await self.capture(channel,event)
                if type(accepted) is not bool:raise TypeError('explicit durable Buzz custody or finite refusal decision required')
                self.grant(channel);results.append([event['id'],accepted])
            complete=len(events)<50
            if events:
                oldest=min((event['created_at'],event['id']) for event in events)
                if state['before_id'] and oldest>=(state['before_ts'],state['before_id']):
                    raise Conflict('Buzz history page did not advance its strict composite cursor')
                state.update(before_ts=oldest[0],before_id=oldest[1])
            page=json.dumps(results,separators=(',',':'))
            self.db.execute('BEGIN IMMEDIATE')
            try:
                current_pin,_=self.grant(channel)
                if current_pin!=pin:raise PermissionError('Buzz history account or grant changed during custody')
                changed=self.db.execute('''UPDATE buzz_history SET floor_ts=?,ceiling_ts=?,before_ts=?,before_id=?,revision=?,complete=?,page=?
                    WHERE channel=? AND pin=? AND revision=?''',(state['floor_ts'],state['ceiling_ts'],state['before_ts'],state['before_id'],
                    state['revision']+1,int(complete),page,channel,pin,state['revision'])).rowcount
                if changed!=1:raise Conflict('concurrent Buzz history cursor requires inspected replay')
                self.grant(channel);self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                raise
            return {'complete':complete,'events':len(events),'retained':sum(accepted for _,accepted in results),'revision':state['revision']+1}
