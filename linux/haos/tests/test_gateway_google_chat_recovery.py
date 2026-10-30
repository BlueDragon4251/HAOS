"""Actual SQLite inspected source/auth recovery; no SDK or network substitutes."""
import hashlib
import json
import time
import pytest

from haos.gateway import Conflict,digest
from haos.gateway_google_chat import scope
from haos.gateway_google_chat_custody import Originals
from haos.gateway_google_chat_recovery import sources,purge_source,retry_auth
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,event,policy


def opened(tmp_path):
    tmp_path.chmod(0o700);store=Originals(tmp_path/'source.sqlite',Redactor([]));selected=policy()
    key=store.retain(selected,'google',account(),json.dumps(event()).encode(),lambda:None)
    profile='google-chat-'+digest(scope(account()))
    return store,selected,key,profile


def decision(profile,row):return {'profile':profile,'id':row['id'],'snapshot_sha256':row['snapshot_sha256'],
    'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True}


def test_original_disposal_requires_withdrawal_and_exact_snapshot_then_compacts_payload_bearing_proof_and_keeps_idempotent_audit(tmp_path):
    store,selected,key,profile=opened(tmp_path);row=sources(store,selected,profile)['sources'][0]
    assert row['state']=='retained' and not row['authentication_reverified'] and not row['private_bytes_returned']
    assert set(row).isdisjoint({'raw','proof','text','credentials'})
    with pytest.raises(PermissionError):purge_source(store,selected,decision(profile,row))
    selected.bindings.clear();row=sources(store,selected,profile)['sources'][0];request=decision(profile,row)
    result=purge_source(store,selected,request);assert result['tombstones_retained'] and not result['network_requested']
    record=store.db.execute('SELECT raw,proof,raw_sha256 FROM google_chat_originals WHERE id=?',(key,)).fetchone()
    assert record['raw']==b'' and set(json.loads(record['proof']))=={'purged','proof_sha256'} and record['raw_sha256']==row['source_sha256']
    assert purge_source(store,selected,request)==result
    with pytest.raises(Conflict):purge_source(store,selected,{**request,'note_sha256':'b'*64})
    assert store.db.execute('SELECT COUNT(*) FROM google_chat_source_owner_events').fetchone()[0]==1
    assert sources(store,selected,profile)['sources'][0]['state']=='purged';store.close()


def test_changed_bytes_invalidate_inspected_snapshot_without_auto_restoration_and_failed_audit_rolls_back_disposal(tmp_path):
    store,selected,key,profile=opened(tmp_path);selected.bindings.clear();row=sources(store,selected,profile)['sources'][0]
    original=store.db.execute('SELECT raw FROM google_chat_originals WHERE id=?',(key,)).fetchone()[0]
    store.db.execute('UPDATE google_chat_originals SET raw=? WHERE id=?',(original+b' ',key))
    with pytest.raises(Conflict):purge_source(store,selected,decision(profile,row))
    current=sources(store,selected,profile)['sources'][0];assert current['state']=='damaged'
    store.db.execute('CREATE TABLE google_chat_source_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)')
    store.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON google_chat_source_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):purge_source(store,selected,decision(profile,current))
    assert store.db.execute('SELECT raw FROM google_chat_originals WHERE id=?',(key,)).fetchone()[0]==original+b' '
    assert not store.db.in_transaction;store.close()


def test_auth_recheck_only_clears_selected_account_block_and_preserves_both_rate_deadlines_without_network(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.sqlite',Redactor([]));selected=policy();value=account();deadline=time.time()+300
    inbox.db.execute('CREATE TABLE google_chat_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)')
    inbox.db.execute('CREATE TABLE google_chat_profile_budget(scope TEXT PRIMARY KEY,not_before REAL NOT NULL)')
    inbox.db.execute('INSERT INTO google_chat_profile_budget VALUES(?,?)',(scope(value),deadline))
    for identity,connector,pin in [('a'*64,'google',digest(['google',value])),('b'*64,'another',digest(['another',value]))]:
        inbox.db.execute('INSERT INTO google_chat_profile_status VALUES(?,?,?,?,?,?)',(identity,connector,pin,'authentication-refused',time.time(),deadline))
    request={'connector':'google','owner_uid':1000,'note_sha256':'c'*64,'confirmed':True}
    result=retry_auth(inbox,selected,'google',value,request)
    assert result['authentication_blocks_cleared']==1 and not result['network_requested'] and not result['message_sent']
    rows=inbox.db.execute('SELECT connector,status,next_attempt FROM google_chat_profile_status ORDER BY connector').fetchall()
    assert [(r['connector'],r['status'],r['next_attempt']) for r in rows]==[('another','authentication-refused',deadline),('google','created',deadline)]
    assert inbox.db.execute('SELECT not_before FROM google_chat_profile_budget').fetchone()[0]==deadline
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_auth_owner_events').fetchone()[0]==1
    with pytest.raises(PermissionError):retry_auth(inbox,selected,'google',value,{**request,'confirmed':False})
    inbox.close()


def reply_group(tmp_path):
    """Actual journal and durable source projection; no SDK/network involved."""
    from haos.gateway_google_chat_text import TextLedger
    import uuid
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'replies.sqlite',Redactor([]));selected=policy();value=account()
    binding=selected.bindings['owner'];envelope={**__import__('haos.gateway_google_chat_admission',fromlist=['approve']).approve(
        selected,'google',value,json.dumps(event()).encode())['envelope'],'text':'/status'}
    source=inbox.admit(selected,'google',envelope,{})
    assert inbox.claim(source,selected) is not None;inbox.complete(source,True)
    inbox.db.execute('CREATE TABLE google_chat_native_projection(source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,envelope_sha256 TEXT NOT NULL)')
    inbox.db.execute('INSERT INTO google_chat_native_projection VALUES(?,?,?,?,?,?)',
        (source,'b'*64,'c'*64,digest(binding),digest(['google',value]),digest(envelope)))
    TextLedger(inbox,'google',value,lambda:selected,lambda:None)
    inbox.db.execute('CREATE TABLE google_chat_delivery_groups(id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,source_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,context_sha256 TEXT NOT NULL,content_sha256 TEXT NOT NULL,parts INTEGER NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,connector TEXT NOT NULL)')
    group='d'*64
    inbox.db.execute('INSERT INTO google_chat_delivery_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (group,binding['id'],digest(binding),digest(value),envelope['message_id'],'c'*64,'e'*64,'f'*64,2,'writing','','google'))
    for index in range(2):
        identity=digest([group,source,index]);body=json.dumps({'text':'private answer part '+str(index),'thread':{'name':binding['thread']}},sort_keys=True,separators=(',',':'))
        inbox.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,binding['id'],digest(binding),digest(value),binding['chat'],body,'client-'+identity[:56],
             str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-chat:'+identity)), 'confirmed' if index==0 else 'writing',
             binding['chat']+'/messages/receipt0' if index==0 else '',time.time(),0))
    return inbox,selected,value,group


def reply_request(view,**change):
    return {'connector':'google','id':view['id'],'part_id':view['parts'][1]['id'],'snapshot_sha256':view['snapshot_sha256'],
        'owner_uid':1000,'note_sha256':'1'*64,'confirmed':True,'confirmed_not_delivered':True,**change}


def test_reply_inventory_hides_bytes_and_retry_is_one_part_audited_idempotent_without_network(tmp_path):
    from haos.gateway_google_chat_recovery import outgoing,approve_retry
    inbox,selected,value,group=reply_group(tmp_path);view=outgoing(inbox,selected,'google',value)['outgoing'][0]
    assert view['confirmed_parts']==1 and view['current_grant'] and view['source_projection_available']
    assert 'private answer' not in json.dumps(view) and not view['private_bytes_returned']
    request=reply_request(view);result=approve_retry(inbox,selected,'google',value,request)
    assert not result['network_requested'] and not result['message_sent'] and result['retry_generation']==1
    assert approve_retry(inbox,selected,'google',value,request)==result
    updated=outgoing(inbox,selected,'google',value)['outgoing'][0]
    assert updated['parts'][0]==view['parts'][0] and updated['parts'][1]['state']=='owner-retry-approved'
    assert updated['parts'][1]['retry_generation']==1 and updated['snapshot_sha256']!=view['snapshot_sha256']
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_reply_owner_events').fetchone()[0]==1
    with pytest.raises(Conflict):approve_retry(inbox,selected,'google',value,{**request,'note_sha256':'2'*64})
    # The same old decision never rearms a consumed attempt, even after crash.
    ledger=__import__('haos.gateway_google_chat_text',fromlist=['TextLedger']).TextLedger(inbox,'google',value,lambda:selected,lambda:None)
    ledger._consume_retry(inbox.db.execute('SELECT * FROM google_chat_text_writes WHERE id=?',(request['part_id'],)).fetchone())
    assert approve_retry(inbox,selected,'google',value,request)==result
    assert inbox.db.execute('SELECT state FROM google_chat_text_writes WHERE id=?',(request['part_id'],)).fetchone()[0]=='writing'
    assert outgoing(inbox,selected,'google',value)['outgoing'][0]['snapshot_sha256']!=view['snapshot_sha256'];inbox.close()


@pytest.mark.parametrize('case',['not-confirmed','wrong-part','confirmed-part','changed-snapshot','withdrawn','rotated','unaudited'])
def test_retry_refuses_unconfirmed_owner_input_changed_account_source_or_grant_and_rolls_back_failed_audit(tmp_path,case):
    from haos.gateway_google_chat_recovery import outgoing,approve_retry
    import sqlite3
    inbox,selected,value,group=reply_group(tmp_path);view=outgoing(inbox,selected,'google',value)['outgoing'][0];request=reply_request(view)
    expected=(PermissionError,Conflict)
    if case=='not-confirmed':request['confirmed_not_delivered']=False
    elif case=='wrong-part':request['part_id']='0'*64
    elif case=='confirmed-part':request['part_id']=view['parts'][0]['id']
    elif case=='changed-snapshot':inbox.db.execute("UPDATE google_chat_text_writes SET body=replace(body,'part 1','part 9') WHERE id=?",(request['part_id'],))
    elif case=='withdrawn':selected.bindings.clear()
    elif case=='rotated':value['service_account']['private_key_id']='b'*40
    elif case=='unaudited':
        inbox.db.execute('CREATE TABLE google_chat_reply_owner_events(receipt TEXT PRIMARY KEY,group_id TEXT NOT NULL,part_id TEXT NOT NULL,generation INTEGER NOT NULL,snapshot_sha256 TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,created_at REAL NOT NULL,consumed_at REAL,UNIQUE(part_id,generation),UNIQUE(part_id,snapshot_sha256))')
        inbox.db.execute("CREATE TRIGGER deny_retry_audit BEFORE INSERT ON google_chat_reply_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
        expected=sqlite3.IntegrityError
    with pytest.raises(expected):approve_retry(inbox,selected,'google',value,request)
    assert not inbox.db.in_transaction
    assert [r[0] for r in inbox.db.execute('SELECT state FROM google_chat_text_writes ORDER BY created_at')]==['confirmed','writing']
    inbox.close()


def test_consumption_audit_failure_rolls_back_before_any_http_and_approval_has_four_attempt_bound(tmp_path):
    from haos.gateway_google_chat_recovery import outgoing,approve_retry
    from haos.gateway_google_chat_text import TextLedger
    inbox,selected,value,group=reply_group(tmp_path);ledger=TextLedger(inbox,'google',value,lambda:selected,lambda:None)
    for generation in range(1,5):
        view=outgoing(inbox,selected,'google',value)['outgoing'][0];request=reply_request(view)
        assert approve_retry(inbox,selected,'google',value,request)['retry_generation']==generation
        row=inbox.db.execute('SELECT * FROM google_chat_text_writes WHERE id=?',(request['part_id'],)).fetchone()
        if generation==1:
            import sqlite3
            inbox.db.execute("CREATE TRIGGER deny_consumption BEFORE UPDATE ON google_chat_reply_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
            with pytest.raises(sqlite3.IntegrityError):ledger._consume_retry(row)
            assert inbox.db.execute('SELECT state FROM google_chat_text_writes WHERE id=?',(row['id'],)).fetchone()[0]=='owner-retry-approved'
            inbox.db.execute('DROP TRIGGER deny_consumption')
        ledger._consume_retry(row)
    view=outgoing(inbox,selected,'google',value)['outgoing'][0]
    with pytest.raises(PermissionError):approve_retry(inbox,selected,'google',value,reply_request(view))
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_reply_owner_events WHERE consumed_at IS NOT NULL').fetchone()[0]==4;inbox.close()
