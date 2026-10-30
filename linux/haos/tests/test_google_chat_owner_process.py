"""Closed Owner result schemas and preserved pre-recovery journal migration."""
from copy import deepcopy
import sqlite3
import pytest

from haos.gateway import digest
from haos.google_chat_owner_process import response
from haos.gateway_google_chat_recovery import sources,outgoing,approve_retry
from haos.gateway_google_chat_text import TextLedger
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,policy
from test_gateway_google_chat_recovery import opened,reply_group,reply_request


def test_real_recovery_snapshots_and_decisions_pass_closed_payload_free_root_response_schema(tmp_path):
    inbox,selected,value,group=reply_group(tmp_path);inventory=outgoing(inbox,selected,'google',value)
    assert response(inventory,'outgoing','google')==inventory
    result=approve_retry(inbox,selected,'google',value,reply_request(inventory['outgoing'][0]))
    assert response(result,'approve-retry','google')==result
    inbox.close()
    original=tmp_path/'original';original.mkdir();store,selected,key,profile=opened(original)
    inventory=sources(store,selected,profile);assert response(inventory,'sources','google')==inventory
    assert response({'profiles':[profile],'history_truncated':False,'network_requested':False,'private_bytes_returned':False},'source-profiles','google')['profiles']==[profile]
    store.close()


@pytest.mark.parametrize('path,change',[
    (['network_requested'],True),(['private_bytes_returned'],True),(['outgoing',0,'body'],'private content'),
    (['outgoing',0,'connector'],'foreign'),(['outgoing',0,'current_grant'],'yes'),(['outgoing',0,'recipient_read_verified'],True),
    (['outgoing',0,'confirmed_parts'],2),(['outgoing',0,'parts',1,'state'],'confirmed'),
    (['outgoing',0,'parts',1,'retry_generation'],True),(['outgoing',0,'parts',0,'receipt'],'spaces/foreign/messages/receipt'),
    (['outgoing',0,'snapshot_sha256'],'0'*64)])
def test_root_rejects_unknown_fields_fabricated_receipts_cross_connector_private_or_changed_snapshots(tmp_path,path,change):
    inbox,selected,value,group=reply_group(tmp_path);inventory=outgoing(inbox,selected,'google',value);target=deepcopy(inventory)
    current=target
    for part in path[:-1]:current=current[part]
    current[path[-1]]=change
    with pytest.raises((ValueError,PermissionError)):response(target,'outgoing','google')
    inbox.close()


def test_previous_private_text_journal_migrates_without_discarding_unknown_or_confirmed_writes(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'legacy.sqlite',Redactor([]))
    inbox.db.execute('CREATE TABLE google_chat_text_writes(id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,parent TEXT NOT NULL,body TEXT NOT NULL,client_id TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)')
    for identity,state in [('a'*64,'writing'),('b'*64,'confirmed')]:
        inbox.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (identity,'owner','c'*64,'d'*64,'spaces/room','{"text":"original"}','client-'+identity[:56],'preserved-request',state,'spaces/room/messages/old' if state=='confirmed' else '',1))
    before=[tuple(row) for row in inbox.db.execute('SELECT * FROM google_chat_text_writes ORDER BY id')]
    TextLedger(inbox,'google',account(),policy,lambda:None)
    after=[tuple(row) for row in inbox.db.execute('SELECT * FROM google_chat_text_writes ORDER BY id')]
    assert [row[:-1] for row in after]==before and all(row[-1]==0 for row in after)
    assert inbox.db.execute('PRAGMA synchronous').fetchone()[0]==2;inbox.close()
