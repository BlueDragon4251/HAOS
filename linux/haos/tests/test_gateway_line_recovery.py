import time

import pytest

from haos.gateway_line_recovery import outgoing
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def journal(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    try:yield inbox
    finally:inbox.close()


def populate(inbox,changes=None):
    inbox.db.execute('CREATE TABLE line_delivery_intents(delivery_id TEXT,attempt INTEGER,state TEXT,receipt TEXT,updated_at REAL)')
    value={'delivery_id':'a'*64,'attempt':1,'state':'confirmed','receipt':'line_push_'+'b'*64,'updated_at':time.time()}
    value.update(changes or {})
    inbox.db.execute('INSERT INTO line_delivery_intents VALUES(?,?,?,?,?)',tuple(value.values()))


def test_line_inspection_missing_schema_and_verified_server_acceptance_are_distinct_from_recipient_receipt(journal):
    assert outgoing(journal)==[]
    populate(journal)
    row=outgoing(journal)[0]
    assert row['server_acceptance_receipt']=='line_push_'+'b'*64 and row['recipient_receipt_verified'] is False
    assert 'fingerprint' not in row and 'text' not in row


@pytest.mark.parametrize('change',[{'delivery_id':'private-path'},{'attempt':0},{'attempt':6},{'state':'invented'},
    {'receipt':'untrusted-proof'},{'state':'writing'},{'state':'uncertain'},{'updated_at':-1},
    {'updated_at':float('inf')},{'updated_at':None}])
def test_private_line_inspection_rejects_invalid_or_misleading_retained_metadata(journal,change):
    populate(journal,change)
    with pytest.raises(ValueError):outgoing(journal)


@pytest.mark.parametrize('change',[None,{'platform':'unknown-plugin'},{'message_id':'raw-unapproved-id'}])
def test_private_line_ingress_inspection_accepts_only_reviewed_platform_and_hashed_identity(journal,change):
    from haos.gateway_line_ingress import PreparedLINEPolicy
    from haos.gateway_raw_recovery import unresolved
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'identity':'owner','capabilities':['create'],'generation':'b'*64,'since':1}]}
    source={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'retained LINE message'}
    journal.admit(PreparedLINEPolicy(config),'line',source,{'event':'retained LINE message'})
    if change:
        key,value=next(iter(change.items()))
        assert key in {'platform','message_id'}
        journal.db.execute(f'UPDATE native_inbox SET {key}=?',(value,))
        with pytest.raises(ValueError):unresolved(journal)
    else:
        row=unresolved(journal)['ingress'][0]
        assert row['platform']=='line' and row['message_id']=='c'*64 and row['state']=='pending'
