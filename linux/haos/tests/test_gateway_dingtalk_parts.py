"""Actual async/SQLite journal tests with synthetic provider outcomes; UID/HTTP are separate."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import time
import pytest

from haos.gateway import Conflict
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_delivery import Publisher
from haos.gateway_dingtalk_parts import Journal
from haos.gateway_dingtalk_reply_process import response
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import account,binding


@pytest.fixture
def fixture(tmp_path):
    grant={**binding(),'allow_outbound_media':True}
    raw={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[deepcopy(grant)]}
    inbox=NativeInbox(tmp_path/'inbox.db',Redactor())
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='dingtalk',inbox=inbox,policy=lambda:PreparedDingTalkPolicy(raw)),
        _haos_dingtalk_value={**account(),'reply_mode':'robot'},_haos_dingtalk_live=True,
        _haos_dingtalk_check=lambda:None,native_health=lambda:{'status':'connected-ws'})
    adapter._haos_dingtalk_publisher=Publisher(adapter)
    try:yield adapter,grant,raw
    finally:inbox.close()


def accepted():return {'state':'confirmed','acceptance_id':'haos-dingtalk-'+'a'*64,'remote_message_id':None,'recipient_read_verified':False}


def test_full_write_intent_precedes_synthetic_provider_and_confirmed_replay_never_dispatches(fixture):
    adapter,grant,_=fixture;parts=Journal(adapter,'reply');db=parts.db;calls=[]
    async def dispatch(current):
        current();assert db.execute('SELECT state FROM dingtalk_media_reply_intents').fetchone()[0]=='writing'
        assert db.execute('PRAGMA synchronous').fetchone()[0]==2
        calls.append(True);return accepted()
    async def run():
        first=await parts.perform(grant,'b'*64,1,0,'c'*64,response,dispatch,lambda:None)
        assert first==accepted()
        assert await parts.perform(grant,'b'*64,2,0,'c'*64,response,dispatch,lambda:None)==first
        with pytest.raises(Conflict):await parts.perform(grant,'b'*64,2,0,'d'*64,response,dispatch,lambda:None)
        assert calls==[True]
    asyncio.run(run())


@pytest.mark.parametrize('outcome',['drop','cancel','invalid-receipt','writing-reopen'])
def test_begun_or_uncertain_part_stays_quarantined_across_attempt_and_actual_journal_reopen(fixture,outcome):
    adapter,grant,_=fixture;parts=Journal(adapter,'reply');calls=[]
    async def run():
        entered=asyncio.Event()
        async def dispatch(current):
            calls.append(True);entered.set()
            if outcome=='cancel':await asyncio.Event().wait()
            if outcome=='invalid-receipt':return {**accepted(),'remote_message_id':'invented'}
            return {'state':'uncertain'}
        task=asyncio.create_task(parts.perform(grant,'b'*64,1,0,'c'*64,response,dispatch,lambda:None))
        await entered.wait()
        if outcome=='cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:assert await task=={'state':'uncertain'}
        if outcome=='writing-reopen':parts.db.execute("UPDATE dingtalk_media_reply_intents SET state='writing'")
        reopened=Journal(adapter,'reply')
        assert await reopened.perform(grant,'b'*64,2,0,'c'*64,response,dispatch,lambda:None)=={'state':'uncertain'}
        assert calls==[True] and parts.db.execute('SELECT state FROM dingtalk_media_reply_intents').fetchone()[0]=='uncertain'
    asyncio.run(run())


def test_native_rate_deadline_blocks_other_parts_and_explicit_auth_clear_cannot_erase_waits(fixture):
    adapter,grant,_=fixture;parts=Journal(adapter,'reply');calls=[]
    async def dispatch(current):calls.append(True);return {'state':'rejected','error':'rate-limited','retry_after':120}
    async def run():
        result=await parts.perform(grant,'b'*64,1,0,'c'*64,response,dispatch,lambda:None)
        assert result['retry_after']==120
        previous=adapter._haos_dingtalk_publisher.health();assert previous['next_attempt']>time.time()+110
        blocked=await parts.perform(grant,'d'*64,1,1,'e'*64,response,dispatch,lambda:None)
        assert blocked['state']=='rejected' and 110<=blocked['retry_after']<=120 and calls==[True]
        parts.backoff('authentication-refused',0)
        assert adapter._haos_dingtalk_publisher.health()['next_attempt']==previous['next_attempt']
        assert adapter._haos_dingtalk_publisher.health()['status']=='authentication-refused'
    asyncio.run(run())


def test_changed_grant_or_removed_output_permission_cannot_reach_provider_callback(fixture):
    adapter,grant,raw=fixture;parts=Journal(adapter,'reply');calls=[]
    async def dispatch(current):calls.append(True);return accepted()
    async def run():
        raw['bindings'][0]['generation']='f'*64
        with pytest.raises(PermissionError):await parts.perform(grant,'b'*64,1,0,'c'*64,response,dispatch,lambda:None)
        raw['bindings'][0]['generation']=grant['generation'];raw['bindings'][0]['allow_outbound_media']=False
        changed=deepcopy(raw['bindings'][0])
        with pytest.raises(PermissionError):await parts.perform(changed,'b'*64,1,0,'c'*64,response,dispatch,lambda:None)
        assert not calls and not parts.db.execute('SELECT * FROM dingtalk_media_reply_intents').fetchall()
    asyncio.run(run())


def test_actual_SQLite_full_during_acceptance_storage_cannot_repeat_a_possibly_completed_upload(fixture):
    from haos.gateway_dingtalk_upload import response as upload_response
    adapter,grant,_=fixture;parts=Journal(adapter,'upload');calls=[]
    async def dispatch(current):
        calls.append(True)
        # Actual page budget after the durable writing row, before receipt bytes.
        pages=parts.db.execute('PRAGMA page_count').fetchone()[0]
        parts.db.execute('PRAGMA max_page_count='+str(pages))
        return {'state':'confirmed','kind':'image','media_id':'$'+'a'*8191,'created_at':int(time.time()*1000)}
    async def run():
        check=lambda result:upload_response(result,{'kind':'image'})
        assert await parts.perform(grant,'b'*64,1,0,'c'*64,check,dispatch,lambda:None)=={'state':'uncertain'}
        assert await Journal(adapter,'upload').perform(grant,'b'*64,2,0,'c'*64,check,dispatch,lambda:None)=={'state':'uncertain'}
        assert calls==[True] and parts.db.execute('SELECT state FROM dingtalk_upload_intents').fetchone()[0]=='uncertain'
    asyncio.run(run())
