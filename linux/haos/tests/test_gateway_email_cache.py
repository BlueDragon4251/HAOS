import copy
import hashlib
import time
import pytest

from haos.gateway import digest,Conflict
from haos.gateway_email import PreparedEmailPolicy
from haos.gateway_email_cache import RawCache
from haos.redaction import Redactor


def fixture(tmp_path):
    scope='mailbox:'+'a'*64
    binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope,'thread':'','identity':'personal','capabilities':['create'],'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
    data=b'From: owner@example.invalid\r\n\r\nAn actual private source body.'
    stamp=time.time()-1;end=data.index(b'\r\n\r\n')+4
    source={'platform':'email','sender':binding['sender'],'chat':binding['chat'],'scope':scope,'thread':'','message_id':'c'*64,'is_bot':False,'text':''}
    resource={'uid':9,'uid_validity':77,'uid_next':10,'size':len(data),'content':data,'sha256':hashlib.sha256(data).hexdigest(),
        'internal_at':stamp,'approval':{'binding_id':'owner','binding_digest':digest(binding),'received_at':stamp,
            'header_sha256':hashlib.sha256(data[:end]).hexdigest(),'rfc_message_id':'<goal@example.invalid>','envelope':source}}
    return config,resource


def test_private_raw_mail_survives_reopen_without_an_agent_path_or_repeated_copy(tmp_path):
    config,resource=fixture(tmp_path);policy=PreparedEmailPolicy(config);path=tmp_path/'raw.db'
    cache=RawCache(path,Redactor())
    identity=cache.put(policy,'email',resource);assert cache.put(policy,'email',resource)==identity
    assert cache.db.execute('SELECT COUNT(*) FROM email_raw_messages').fetchone()[0]==1
    cache.close();cache=RawCache(path,Redactor())
    try:assert cache.get(policy,identity)==resource
    finally:cache.close()
    assert path.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('change',['grant','scope','connector','bytes','header','reflection'])
def test_raw_mail_custody_refuses_changed_route_content_and_private_credentials(tmp_path,change):
    config,resource=fixture(tmp_path);cache=RawCache(tmp_path/'raw.db',Redactor(['private-secret-fixture']))
    try:
        identity=cache.put(PreparedEmailPolicy(config),'email',resource)
        if change in {'grant','scope','connector'}:
            altered=copy.deepcopy(config)
            if change=='grant':altered['bindings'][0]['generation']='d'*64
            elif change=='scope':altered['bindings'][0]['scope']='mailbox:'+'e'*64
            else:altered['connectors'][0]['id']='other';altered['bindings'][0]['connector']='other'
            with pytest.raises(PermissionError):cache.get(PreparedEmailPolicy(altered),identity)
        else:
            bad=copy.deepcopy(resource)
            if change=='bytes':bad['content']=b'changed body'
            elif change=='header':bad['approval']['header_sha256']='f'*64
            else:
                bad['content']+=b'private-secret-fixture';bad['size']=len(bad['content']);bad['sha256']=hashlib.sha256(bad['content']).hexdigest()
            with pytest.raises((ValueError,PermissionError,Conflict)):cache.put(PreparedEmailPolicy(config),'email',bad)
        assert cache.get(PreparedEmailPolicy(config),identity)==resource
        assert cache.db.execute('SELECT COUNT(*) FROM email_raw_messages').fetchone()[0]==1
    finally:cache.close()


def retained_input(tmp_path):
    from haos.gateway_raw import NativeInbox
    config,resource=fixture(tmp_path);policy=PreparedEmailPolicy(config)
    cache=RawCache(tmp_path/'raw.db',Redactor());inbox=NativeInbox(tmp_path/'native.db',Redactor())
    identity=cache.put(policy,'email',resource)
    envelope={**resource['approval']['envelope'],'text':'A retained source goal.'}
    key=inbox.admit(policy,'email',envelope,{'raw_id':identity},received_at=resource['internal_at'])
    return config,resource,policy,cache,inbox,identity,key


def purge_request(cache,inbox,policy,identity):
    row=next(item for item in cache.owner_inventory(inbox,policy)['sources'] if item['id']==identity)
    return {'id':identity,'snapshot_sha256':row['snapshot_sha256'],'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True}


def test_owner_purge_only_compacts_inspected_completed_source_and_preserves_immutable_tombstone(tmp_path):
    config,resource,policy,cache,inbox,identity,key=retained_input(tmp_path)
    try:
        assert inbox.claim(key,policy);inbox.complete(key,True)
        decision=purge_request(cache,inbox,policy,identity)
        result=cache.owner_purge(inbox,policy,decision)
        assert result['removed_payload_bytes']==len(resource['content']) and result['tombstone_and_audit_retained']
        assert cache.db.execute('SELECT sha256,length(data) FROM email_raw_messages WHERE id=?',(identity,)).fetchone()[:]==(resource['sha256'],0)
        assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='committed'
        assert cache.owner_purge(inbox,policy,decision)['removed_payload_bytes']==0
        assert cache.db.execute('SELECT COUNT(*) FROM email_raw_owner_events').fetchone()[0]==1
        assert cache.put(policy,'email',resource)==identity  # Replay cannot rehydrate inspected/purged bytes.
        with pytest.raises(PermissionError):cache.get(policy,identity)
    finally:inbox.close();cache.close()


def test_pending_source_or_stale_inspection_cannot_be_purged_or_execute_as_new_input(tmp_path):
    config,resource,policy,cache,inbox,identity,key=retained_input(tmp_path)
    try:
        decision=purge_request(cache,inbox,policy,identity)
        with pytest.raises(PermissionError):cache.owner_purge(inbox,policy,decision)
        assert inbox.claim(key,policy);inbox.complete(key,True)
        with pytest.raises(Conflict):cache.owner_purge(inbox,policy,decision)
        assert cache.get(policy,identity)==resource
    finally:inbox.close();cache.close()


def test_unadmitted_source_requires_owner_grant_withdrawal_before_explicit_purge(tmp_path):
    from haos.gateway_raw import NativeInbox
    config,resource=fixture(tmp_path);policy=PreparedEmailPolicy(config)
    cache=RawCache(tmp_path/'raw.db',Redactor());inbox=NativeInbox(tmp_path/'native.db',Redactor())
    try:
        identity=cache.put(policy,'email',resource)
        with pytest.raises(PermissionError):cache.owner_purge(inbox,policy,purge_request(cache,inbox,policy,identity))
        config['bindings'][0]['generation']='e'*64;policy=PreparedEmailPolicy(config)
        assert cache.owner_purge(inbox,policy,purge_request(cache,inbox,policy,identity))['removed_payload_bytes']==len(resource['content'])
    finally:inbox.close();cache.close()


def test_failed_purge_transaction_preserves_source_bytes_and_owner_recovery_record(tmp_path):
    import sqlite3
    config,resource,policy,cache,inbox,identity,key=retained_input(tmp_path)
    try:
        assert inbox.claim(key,policy);inbox.complete(key,True)
        cache.db.execute("CREATE TRIGGER deny_raw_purge BEFORE UPDATE ON email_raw_messages BEGIN SELECT RAISE(FAIL,'fixture purge failure'); END")
        with pytest.raises(sqlite3.IntegrityError):cache.owner_purge(inbox,policy,purge_request(cache,inbox,policy,identity))
        assert cache.get(policy,identity)==resource
        assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='committed'
    finally:inbox.close();cache.close()


def test_owner_source_selector_is_opaque_and_partial_profiles_do_not_create_or_hide_ledgers(tmp_path):
    from haos.gateway_raw import NativeInbox
    from haos.gateway_email_recovery import sources,purge_source
    config,resource=fixture(tmp_path);policy=PreparedEmailPolicy(config)
    parent=tmp_path/'profiles';parent.mkdir(mode=0o700)
    profile='email-'+'a'*64;directory=parent/profile;directory.mkdir(mode=0o700)
    incomplete=parent/('email-'+'b'*64);incomplete.mkdir(mode=0o700)
    cache=RawCache(directory/'raw.db',Redactor());inbox=NativeInbox(tmp_path/'native.db',Redactor())
    try:
        identity=cache.put(policy,'email',resource);cache.close()
        index=sources(inbox,policy,parent=parent)
        assert len(index['profiles'])==2 and not index['network_requested']
        assert next(item for item in index['profiles'] if item['profile']==profile)['records']==1
        assert next(item for item in index['profiles'] if item['profile']!=profile)['status']=='incomplete-profile'
        assert not (incomplete/'raw.db').exists()
        with pytest.raises(ValueError):sources(inbox,policy,'../raw.db',parent=parent)
        config['bindings'][0]['generation']='e'*64;policy=PreparedEmailPolicy(config)
        inspection=sources(inbox,policy,profile,parent=parent)['sources'][0]
        result=purge_source(inbox,policy,{'profile':profile,'id':identity,'snapshot_sha256':inspection['snapshot_sha256'],
            'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True},parent=parent)
        assert result['removed_payload_bytes']==len(resource['content'])
        assert sources(inbox,policy,profile,parent=parent)['sources'][0]['state']=='purged'
        linked=parent/('email-'+'c'*64);linked.symlink_to(directory,target_is_directory=True)
        with pytest.raises(PermissionError):sources(inbox,policy,linked.name,parent=parent)
    finally:inbox.close()
