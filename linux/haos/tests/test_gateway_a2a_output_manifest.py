"""Controller whole-event projection custody and actual SQL rollback contracts."""
import asyncio
import json
import sqlite3

import pytest

from haos.controller import Controller
from haos.gateway import Conflict,digest
from haos.gateway_a2a import PreparedA2APolicy
from haos.gateway_outbound import Exports
from haos.store import MissionStore


@pytest.fixture
def output(tmp_path):
    binding={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-output','scope':'a2a:'+'a'*64,'thread':'',
        'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding]}
    policy=lambda:PreparedA2APolicy(config)
    store=MissionStore(tmp_path/'missions.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
    envelope={'platform':'a2a','sender':'alice','chat':binding['chat'],'scope':binding['scope'],'thread':'',
        'message_id':'source-output','text':'Controlled projection contract.','is_bot':False}
    try:
        result=asyncio.run(controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'a2a','envelope':envelope,
            'binding':{'binding_id':binding['id'],'binding_digest':digest(binding)}}}))
        mid=result['mission_id'];engine=controller.gateway
        receipt=engine.next_delivery(policy());engine.acknowledge(policy(),receipt['id'],{'attempt':receipt['attempt'],'status':'delivered','message_id':'receipt'})
        assert store.claim()['id']==mid
        body='x'*1710+'\n```text\nMEDIA:./private-example.key\n```\nReal file.\nMEDIA:./result.csv\n'+('full Unicode ä '*6000)
        store.settle(mid,'completed',result=body);deliveries=[]
        while (row:=engine.next_delivery(policy())) is not None:
            if row['event_context']['kind']=='mission.completed':deliveries.append(row)
        assert len(deliveries)>40
        yield store,Exports(controller),deliveries,config
    finally:store.close()


def params(row):return {'delivery':row['id'],'attempt':row['attempt']}


def test_whole_group_is_retained_once_with_fences_and_unicode_before_selecting_individual_parts(output):
    store,exports,deliveries,_=output
    values=[exports.manifest(params(row)) for row in reversed(deliveries)]
    assert [p for value in values for p in value['paths']]==['./result.csv']
    text=''.join(reversed([value['text'] for value in values]))
    assert 'MEDIA:./private-example.key' in text and 'MEDIA:./result.csv' not in text and text.count('full Unicode ä ')==6000
    assert store.db.execute('SELECT COUNT(*) FROM gateway_output_manifests').fetchone()[0]==1
    assert store.db.execute('SELECT COUNT(*) FROM gateway_output_projections').fetchone()[0]==len(deliveries)


def test_real_projection_insert_failure_rolls_back_every_partial_row_and_retries_exact_original(output):
    store,exports,deliveries,_=output
    store.db.execute("CREATE TRIGGER fail_projection BEFORE INSERT ON gateway_output_projections WHEN NEW.part=1 BEGIN SELECT RAISE(ABORT,'fixture failed projection'); END")
    with pytest.raises(sqlite3.IntegrityError):exports.manifest(params(deliveries[0]))
    assert store.db.execute('SELECT COUNT(*) FROM gateway_output_manifests').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM gateway_output_projections').fetchone()[0]==0
    store.db.execute('DROP TRIGGER fail_projection')
    assert exports.manifest(params(deliveries[0]))['group_sha256']==deliveries[0]['event_context']['group_sha256']


def test_changed_retained_projection_proof_is_refused(output):
    store,exports,deliveries,_=output;exports.manifest(params(deliveries[0]))
    row=store.db.execute('SELECT manifest_id,part,projection FROM gateway_output_projections LIMIT 1').fetchone()
    changed=json.loads(row['projection']);changed['paths']=['./owner-secret.key']
    store.db.execute('UPDATE gateway_output_projections SET projection=? WHERE manifest_id=? AND part=?',
        (json.dumps(changed),row['manifest_id'],row['part']))
    with pytest.raises(Conflict):exports.manifest(params(deliveries[row['part']]))


def test_cached_projection_still_requires_current_root_owner_grant_epoch(output):
    _,exports,deliveries,config=output;exports.manifest(params(deliveries[0]))
    config['bindings'][0]['generation']='b'*64
    with pytest.raises(PermissionError):exports.manifest(params(deliveries[0]))
