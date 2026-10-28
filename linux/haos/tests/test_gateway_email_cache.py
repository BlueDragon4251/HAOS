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
