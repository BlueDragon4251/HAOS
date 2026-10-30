"""Closed SDK read capabilities remain usable without optional Lark imports."""
from types import SimpleNamespace
import time
import pytest
from haos.gateway_feishu import DOMAINS
from haos.gateway_feishu_http import Boundary,Failure,ScopedCache
from haos.redaction import Redactor
from test_gateway_feishu import account


def fixture():
    value=account();state={'current':True,'approved':True}
    def current():
        if not state['current']:raise PermissionError('withdrawn fixture publication')
    boundary=Boundary(value,current,lambda *_:state['approved'],Redactor())
    config=SimpleNamespace(app_id=value['app_id'],app_secret=value['app_secret'],domain=DOMAINS[value['domain']])
    return boundary,config,state


@pytest.mark.parametrize('purpose,target',[
    ('write',{}),('account',{'message_id':'om_'+'a'*32}),('message',{}),
    ('message',{'message_id':'../escape'}),('message',{'message_id':True}),('account',[]),
])
def test_only_exact_read_operations_are_capabilities(purpose,target):
    boundary,config,_=fixture()
    with pytest.raises(Failure,match='private Feishu'):
        with boundary.operation(config,purpose,target):raise AssertionError('invalid capability admitted')


@pytest.mark.parametrize('method,suffix,kwargs',[
    ('POST','/open-apis/im/v1/messages',{}),('GET','/open-apis/bot/v3/info?scope=other',{}),
    ('GET','/open-apis/bot/v3/info#fragment',{}),('GET','/open-apis/drive/v1/files',{}),
    ('GET','/open-apis/bot/v3/info',{'verify':False}),('GET','/open-apis/bot/v3/info',{'params':{'scope':'other'}}),
    ('GET','/open-apis/bot/v3/info',{'headers':{'Host':'other.invalid'}}),
    ('GET','/open-apis/bot/v3/info',{'headers':{'Transfer-Encoding':'chunked'}}),
    ('GET','/open-apis/bot/v3/info',{'headers':{'Authorization':'Bearer untracked-fixture-value'}}),
    ('POST','/open-apis/auth/v3/tenant_access_token/internal',{'data':b'{}'}),
])
def test_unapproved_request_never_invokes_network(method,suffix,kwargs):
    boundary,config,_=fixture();calls=[]
    with boundary.operation(config,'account',{}):
        with pytest.raises(Failure):boundary.request(lambda *_a,**_k:calls.append(True),method,boundary.origin+suffix,**kwargs)
    assert calls==[]


def test_revocation_client_mutation_deadline_and_context_cleanup_are_immediate():
    boundary,config,state=fixture()
    with boundary.operation(config,'account',{}):
        from haos.gateway_feishu_http import active
        state['approved']=False
        with pytest.raises(Failure) as error:active()
        assert error.value.kind=='withdrawn-grant';state['approved']=True
        state['current']=False
        with pytest.raises(PermissionError):active()
        state['current']=True;config.app_secret+='-changed'
        with pytest.raises(Failure) as error:active()
        assert error.value.kind=='changed-client';config.app_secret=boundary.value['app_secret']
        active()['deadline']=time.monotonic()-1
        with pytest.raises(Failure) as error:active()
        assert error.value.kind=='expired-capability'
    with pytest.raises(Failure) as error:active()
    assert error.value.kind=='missing-capability'


def test_native_cache_cannot_inject_unobserved_token_or_another_app_key():
    boundary,config,_=fixture();writes=[]
    cache=ScopedCache(SimpleNamespace(get=lambda _key:'untracked-fixture-value',set=lambda *args:writes.append(args)))
    key='self_tenant_token:'+boundary.value['app_id']
    with boundary.operation(config,'account',{}):
        assert cache.get(key) is None
        with pytest.raises(Failure):cache.get('self_tenant_token:other-app')
        with pytest.raises(Failure):cache.set(key,'untracked-fixture-value',int(time.time())+3600)
    assert writes==[]
