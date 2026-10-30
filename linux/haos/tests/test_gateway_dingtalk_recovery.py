"""Inspected offline decisions use actual SQLite; owner handoff/UID integration is separate."""
from copy import deepcopy
import json
import time
from types import SimpleNamespace
import pytest

from haos.gateway import Conflict
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_delivery import Publisher
from haos.gateway_dingtalk_recovery import outgoing,accounts,approve_retry
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import account,binding


@pytest.fixture
def ledger(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='dingtalk',inbox=inbox),_haos_dingtalk_value=account())
    publisher=Publisher(adapter);now=time.time()
    inbox.db.execute('INSERT INTO dingtalk_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
        ('a'*64,1,'dingtalk',publisher.credential_scope,'b'*64,'uncertain','','',now,now))
    policy=PreparedDingTalkPolicy({'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[binding()]})
    try:yield inbox,policy
    finally:inbox.close()


def request(inbox):return {'connector':'dingtalk','delivery_id':'a'*64,'attempt':1,'snapshot_sha256':outgoing(inbox)[0]['snapshot_sha256'],
    'owner_uid':1000,'note_sha256':'c'*64,'confirmed':True,'confirmed_not_delivered':True}


def test_inspected_non_delivery_decision_is_durable_idempotent_and_does_not_send(ledger):
    inbox,policy=ledger;decision=request(inbox)
    result=approve_retry(inbox,policy,decision)
    assert result['private_retry_approved'] and result['controller_reconciliation_still_required'] and result['network_requested'] is False
    assert outgoing(inbox)[0]['state']=='owner-retry-approved'
    assert approve_retry(inbox,policy,decision)==result
    assert inbox.db.execute('SELECT COUNT(*) FROM dingtalk_delivery_owner_events').fetchone()[0]==1
    with pytest.raises(Conflict):approve_retry(inbox,policy,{**decision,'note_sha256':'d'*64})
    assert 'private-dingtalk-fixture' not in json.dumps(outgoing(inbox)+accounts(inbox))


@pytest.mark.parametrize('change',[{'confirmed':False},{'confirmed_not_delivered':False},{'confirmed':1},
    {'owner_uid':True},{'owner_uid':-1},{'snapshot_sha256':'d'*64},{'attempt':5},{'connector':'unknown'},
    {'note_sha256':'not an inspected evidence hash'},{'extra':'unreviewed flag'}])
def test_no_ambiguous_owner_confirmation_stale_inspection_or_unauthorized_connector_releases_write(ledger,change):
    inbox,policy=ledger;decision=request(inbox)
    with pytest.raises((PermissionError,Conflict)):approve_retry(inbox,policy,{**decision,**change})
    assert outgoing(inbox)[0]['state']=='uncertain'


def test_changed_or_confirmed_receipt_and_removed_read_grant_cannot_be_released(ledger):
    inbox,policy=ledger;decision=request(inbox)
    inbox.db.execute('UPDATE dingtalk_delivery_intents SET updated_at=updated_at+1')
    with pytest.raises(Conflict):approve_retry(inbox,policy,decision)
    inbox.db.execute("UPDATE dingtalk_delivery_intents SET state='confirmed',receipt=?",('haos-dingtalk-'+'e'*64,))
    with pytest.raises(PermissionError):approve_retry(inbox,policy,request(inbox))
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{**binding(),'capabilities':['create']}]}
    with pytest.raises(PermissionError):approve_retry(inbox,PreparedDingTalkPolicy(config),request(inbox))
    assert outgoing(inbox)[0]['state']=='confirmed'


def test_private_raw_error_or_damaged_account_metadata_is_never_returned_to_owner_inventory(ledger):
    inbox,_=ledger
    inbox.db.execute("UPDATE dingtalk_delivery_intents SET error='raw private response'")
    with pytest.raises(Conflict):outgoing(inbox)
    inbox.db.execute("UPDATE dingtalk_delivery_backoff SET next_attempt=-1")
    with pytest.raises(Conflict):accounts(inbox)


def test_auth_recheck_is_exact_account_scoped_preserves_waits_and_uncertain_writes(ledger):
    from haos.gateway_dingtalk_recovery import retry_auth
    inbox,policy=ledger;now=time.time();future=now+600
    inbox.db.execute('CREATE TABLE dingtalk_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)')
    for identity,scope,status in [('a','a'*64,'authentication-refused'),('b','b'*64,'authentication-refused'),('c','a'*64,'rate-limited')]:
        inbox.db.execute('INSERT INTO dingtalk_profile_status VALUES(?,?,?,?,?,?)',(identity,'dingtalk',scope,status,now,future))
    account=inbox.db.execute('SELECT account_scope FROM dingtalk_delivery_backoff').fetchone()[0]
    inbox.db.execute("UPDATE dingtalk_delivery_backoff SET status='authentication-refused',next_attempt=?",(future,))
    request={'connector':'dingtalk','credential_scope':'a'*64,'account_scope':account,'owner_uid':1000,'note_sha256':'e'*64}
    before=outgoing(inbox)
    assert retry_auth(inbox,policy,request)['authentication_blocks_cleared']==2
    assert retry_auth(inbox,policy,request)['authentication_blocks_cleared']==0
    rows={row['identity']:dict(row) for row in inbox.db.execute('SELECT * FROM dingtalk_profile_status')}
    assert rows['a']['status']=='created' and rows['b']['status']=='authentication-refused' and rows['c']['status']=='rate-limited'
    assert all(row['next_attempt']==future for row in rows.values())
    assert accounts(inbox)[0]['status']=='ready' and accounts(inbox)[0]['next_attempt']==future
    assert outgoing(inbox)==before and inbox.db.execute('SELECT COUNT(*) FROM dingtalk_auth_owner_events').fetchone()[0]==1
    from haos.gateway_raw_recovery import unresolved
    assert len([row for row in unresolved(inbox)['transport'] if row['platform']=='dingtalk'])==3
