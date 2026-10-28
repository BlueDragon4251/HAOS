import copy
from urllib.parse import urlencode
import pytest

from haos.gateway_sms import PreparedSMSPolicy,credentials,envelope,form,scope,validate_binding


def values():return {'account_sid':'AC'+'a'*32,'from_number':'+12025550100'}


def message():return {'AccountSid':'AC'+'a'*32,'MessageSid':'SM'+'d'*32,'From':'+12025550101','To':'+12025550100','Body':'  a real SMS goal  ','NumMedia':'0'}


def config():
    return {'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{'id':'owner','connector':'sms','sender':'+12025550101',
        'chat':'+12025550101','scope':scope(values()),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'c'*64,'since':1}]}


def test_prepared_sms_is_not_automatically_public_and_requires_exact_phone_scope():
    from haos.gateway import GatewayPolicy
    with pytest.raises(ValueError):GatewayPolicy(config())
    policy=PreparedSMSPolicy(config());source=envelope(message(),values())
    assert source['text']=='a real SMS goal' and source['scope']==scope(values())
    assert policy.authorize('sms',source)['id']=='owner'
    with pytest.raises(PermissionError):policy.authorize('sms',{**source,'sender':'+12025550199'})


@pytest.mark.parametrize('changes',[{'sender':'anonymous'},{'chat':'+12025550199'},{'scope':'any'},{'thread':'forged'},
    {'sender':'+12025550100','chat':'+12025550100'},{'since':None},{'generation':None}])
def test_sms_rejects_display_names_changed_recipient_threads_and_missing_epochs(changes):
    c=config();c['bindings'][0].update(changes)
    with pytest.raises(ValueError):PreparedSMSPolicy(c)


@pytest.mark.parametrize('raw',[b'From=one&From=two',b'Body=%ZZ',b'Body=%ff',b'Body=%f',b'no-equals',b'=missing-name',
    b'Body=x&bad.key=y',b'Body=x&'+b'a='*33000,b'Body='+b'x'*65536])
def test_ambiguous_or_unbounded_sms_forms_are_refused_before_optional_sdk_import(raw):
    with pytest.raises((ValueError,UnicodeError)):form(raw)


def test_sms_form_preserves_signed_unicode_and_literal_plus():
    original=message();original['Body']='Grüße + 😀'
    assert form(urlencode(original).encode())==original


@pytest.mark.parametrize('change',[{'AccountSid':'AC'+'f'*32},{'MessageSid':'../private'},{'From':'display name'},
    {'To':'+12025550199'},{'Body':''},{'Body':'x'*1601},{'NumMedia':'5'},{'MediaUrl0':'http://127.0.0.1/private'}])
def test_unreviewed_sms_identity_text_or_media_cannot_become_a_mission(change):
    item=message();item.update(change)
    with pytest.raises(ValueError):envelope(item,values())


@pytest.mark.parametrize('change',[{'account_sid':'AC../private'},{'auth_token':'bad'},{'from_number':'alice'},
    {'port':True},{'port':443},{'unexpected':'field'}])
def test_invalid_private_sms_settings_fail_before_optional_tls_or_sdk_work(change):
    value={**values(),'auth_token':'b'*32,'port':8647,'tls':{}};value.update(change)
    with pytest.raises(ValueError):credentials(value)


def test_recovery_pages_preserve_exact_account_sender_receiver_and_date_filters():
    from haos.gateway_sms_recovery import query,list_path
    value=values();binding=config()['bindings'][0]
    first=query(value,binding)
    assert list_path(first,value)
    continuation='/2010-04-01/Accounts/'+value['account_sid']+first
    continuation+='&PageToken=opaque%2Btoken&Page=1'
    assert list_path(query(value,binding,continuation),value)
    for bad in ['https://foreign.invalid'+continuation,continuation.replace('From=%2B12025550101','From=%2B12025550199'),
            continuation.replace(value['account_sid'],'AC'+'f'*32),continuation+'&From=%2B12025550101',
            continuation+'&unexpected=private',continuation.replace('Page=1','Page=-1'),continuation.replace('PageToken=opaque%2Btoken','PageToken='),
            continuation+'#fragment']:
        with pytest.raises(PermissionError):query(value,binding,bad)
    assert not list_path('/Messages.json?From=owner',value)
    assert not list_path(first.replace('PageSize=10','PageSize=1000'),value)
    assert not list_path(first.replace('To=%2B12025550100','To=%2B12025550199'),value)


def test_sms_offline_auth_recovery_is_audited_and_keeps_rate_limits_and_uncertain_writes(tmp_path):
    import time
    from haos.gateway_raw import NativeInbox
    from haos.gateway_raw_recovery import retry_sms_auth,unresolved
    from haos.redaction import Redactor
    policy=PreparedSMSPolicy(config());inbox=NativeInbox(tmp_path/'native.db',Redactor())
    try:
        db=inbox.db;now=time.time();deadline=now+120
        db.execute('CREATE TABLE sms_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
        for index,state in enumerate(['authentication-refused','identity-refused','rate-limited','revoked']):
            db.execute('INSERT INTO sms_profile_status VALUES(?,?,?,?,?,?)',(str(index),'sms','private-scope',state,now,deadline))
        db.execute('CREATE TABLE sms_delivery_intents(delivery_id TEXT,attempt INTEGER,fingerprint TEXT,state TEXT,receipt TEXT,updated_at REAL)')
        db.execute('INSERT INTO sms_delivery_intents VALUES(?,?,?,?,?,?)',('e'*64,1,'private-fingerprint','uncertain','',now))
        request={'connector':'sms','owner_uid':1000,'note_sha256':'f'*64}
        result=retry_sms_auth(inbox,policy,request)
        assert result=={'connector':'sms','authentication_blocks_cleared':2,'network_requested':False}
        assert [row[0] for row in db.execute('SELECT status FROM sms_profile_status ORDER BY identity')]==['created','created','rate-limited','revoked']
        assert all(row[0]==deadline for row in db.execute('SELECT next_attempt FROM sms_profile_status'))
        event=db.execute('SELECT owner_uid,decision,changed,note_sha256 FROM sms_owner_events').fetchone()
        assert tuple(event)==(1000,'retry-auth',2,'f'*64)
        metadata=unresolved(inbox)
        assert len(metadata['transport'])==4 and metadata['native_outgoing'][0]['state']=='uncertain'
        assert metadata['native_outgoing'][0]['recipient_receipt_verified'] is False
        assert 'private-' not in __import__('json').dumps(metadata)
        assert retry_sms_auth(inbox,policy,request)['authentication_blocks_cleared']==0
        with pytest.raises(ValueError,match='exact gateway connector'):retry_sms_auth(inbox,PreparedSMSPolicy({'version':1,'connectors':[],'bindings':[]}),request)
    finally:inbox.close()
