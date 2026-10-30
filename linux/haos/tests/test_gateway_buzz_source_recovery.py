"""Actual SQLite disposal and changed-grant cursor recovery, no SDK or network."""
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from haos.gateway import GatewayPolicy,Conflict,digest
from haos.gateway_buzz import scope
from haos.gateway_buzz_cache import RawEvents
from haos.gateway_buzz_history import History
from haos.gateway_buzz_source_recovery import sources,purge,history,reset_history
from haos.redaction import Redactor


@pytest.fixture
def ledgers(tmp_path):
    value={'private_key':'1'*64,'public_key':'2'*64,'relay_url':'https://buzz.fixture.invalid',
        'channels':['01234567-89ab-4cde-8012-3456789abcde']}
    binding={'id':'owner','connector':'buzz','sender':'3'*64,'chat':value['channels'][0],'scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[binding]};current=lambda:GatewayPolicy(config)
    raw=RawEvents(tmp_path/'originals.db',Redactor(),current);data=b'private retained fixture original'
    metadata=json.dumps({'envelope':{'text':'private retained fixture original','resource_url':'https://private.fixture.invalid/input'}})
    raw.db.execute('INSERT INTO buzz_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ('b'*64,'c'*64,'buzz','d'*64,'owner',digest(binding),digest(['buzz',value]),metadata,
            hashlib.sha256(data).hexdigest(),data,1793332800,'',1793332800))
    async def run(*args,**kwargs):return 0,'[]',''
    async def capture(*args):raise AssertionError('no original expected in empty fixture history')
    reader=SimpleNamespace(connector='buzz',value=value,current=current,peers=lambda:current().bindings.keys(),run=run)
    index=History(tmp_path/'history.db',reader,Redactor(),capture);asyncio.run(index.step(value['channels'][0]))
    profile=scope(value).replace('buzz:','buzz-',1)
    try:yield raw,index,reader,config,profile
    finally:raw.close();index.close()


def request(view,**parts):return {'profile':view['profile'],'snapshot_sha256':view['snapshot_sha256'],
    'owner_uid':1000,'note_sha256':'f'*64,'confirmed':True,**parts}


def test_original_disposal_requires_withdrawal_compacts_payload_bearing_proof_and_retains_idempotent_tombstone(ledgers):
    raw,_,reader,config,profile=ledgers;row=sources(raw.store,reader.current(),profile)['sources'][0]
    with pytest.raises(PermissionError):purge(raw.store,reader.current(),request(row,id=row['id']))
    config['bindings']=[];row=sources(raw.store,reader.current(),profile)['sources'][0];decision=request(row,id=row['id'])
    result=purge(raw.store,reader.current(),decision);assert purge(raw.store,reader.current(),decision)==result
    stored=raw.db.execute('SELECT data,metadata FROM buzz_raw_events').fetchone()
    assert stored['data']==b'' and 'private retained fixture original' not in stored['metadata']
    assert 'private.fixture.invalid' not in stored['metadata'] and json.loads(stored['metadata'])['purged'] is True
    assert result['tombstones_retained'] is True and result['network_requested'] is False
    assert sources(raw.store,reader.current(),profile)['sources'][0]['purged'] is True


def test_source_byte_change_invalidates_prior_inspection_and_new_view_reports_damaged_original(ledgers):
    raw,_,reader,config,profile=ledgers;config['bindings']=[]
    row=sources(raw.store,reader.current(),profile)['sources'][0];raw.db.execute("UPDATE buzz_raw_events SET data=x'00'")
    with pytest.raises(Conflict):purge(raw.store,reader.current(),request(row,id=row['id']))
    assert sources(raw.store,reader.current(),profile)['sources'][0]['state']=='damaged'


def test_current_grant_cursor_cannot_be_reseeded_and_new_exact_grant_requires_explicit_fresh_inspection(ledgers):
    _,index,reader,config,profile=ledgers
    row=history(index.store,reader,profile)['history'][0]
    assert row['state']=='current' and row['reset_allowed'] is False
    with pytest.raises(PermissionError):reset_history(index.store,reader,request(row,channel=row['channel']))
    config['bindings'][0].update(generation='e'*64,since=5000)
    with pytest.raises(Conflict):asyncio.run(index.step(reader.value['channels'][0]))
    row=history(index.store,reader,profile)['history'][0];assert row['state']=='grant-changed' and row['current_earliest']==5
    decision=request(row,channel=row['channel']);result=reset_history(index.store,reader,decision)
    assert reset_history(index.store,reader,decision)==result and result['network_requested'] is False
    saved=index.db.execute('SELECT floor_ts,revision,complete FROM buzz_history').fetchone()
    assert tuple(saved)==(5,2,0)
    assert index.db.execute('SELECT COUNT(*) FROM buzz_history_owner_events').fetchone()[0]==1


def test_historical_account_profile_cannot_be_rebound_to_new_account_history(ledgers):
    _,index,reader,config,_=ledgers;old='buzz-'+'a'*64
    config['bindings'][0].update(generation='e'*64,since=5000)
    row=history(index.store,reader,old)['history'][0]
    assert row['current_pin'] is None and row['reset_allowed'] is False and row['state']=='unpaired'
    with pytest.raises(PermissionError):reset_history(index.store,reader,request(row,channel=row['channel']))
