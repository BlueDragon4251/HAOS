"""Native chunks cannot inherit changed grants or another connector's authority."""
from types import SimpleNamespace

import pytest

from haos.gateway import GatewayPolicy,digest
from haos.gateway_delivery_authority import current_delivery


def fixture():
    config={'version':1,'connectors':[{'id':'bot','platform':'slack'},{'id':'other','platform':'slack'}],
        'bindings':[{'id':key,'connector':connector,'sender':'U42','chat':'C123','scope':'T999','thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64}
            for key,connector in [('paired','bot'),('foreign','other')]]}
    policy=lambda:GatewayPolicy(config)
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='bot',policy=policy))
    metadata={'haos_scope':'T999','haos_binding':{'binding_id':'paired','binding_digest':digest(config['bindings'][0])}}
    return config,adapter,metadata


def test_inflight_native_delivery_cannot_inherit_regrant_by_mutating_caller_metadata():
    config,adapter,metadata=fixture()
    current=current_delivery(adapter,'slack','C123',metadata);current()
    config['bindings'][0]['generation']='b'*64
    metadata['haos_binding']['binding_digest']=digest(config['bindings'][0])
    with pytest.raises(PermissionError):current()
    # Only a new explicit operation may receive the new owner capability.
    current_delivery(adapter,'slack','C123',metadata)()


def test_current_delivery_refuses_another_connectors_otherwise_identical_valid_grant():
    config,adapter,metadata=fixture()
    metadata['haos_binding']={'binding_id':'foreign','binding_digest':digest(config['bindings'][1])}
    with pytest.raises(PermissionError):current_delivery(adapter,'slack','C123',metadata)


def test_current_delivery_refuses_valid_binding_digest_without_owner_read_permission():
    config,adapter,metadata=fixture()
    config['bindings'][0]['capabilities']=['create']
    metadata['haos_binding']['binding_digest']=digest(config['bindings'][0])
    with pytest.raises(PermissionError):current_delivery(adapter,'slack','C123',metadata)


@pytest.mark.parametrize('change',['withdraw','scope','thread','rights','identity','policy_callback'])
def test_native_delivery_rechecks_independent_owner_authority_on_every_operation(change):
    config,adapter,metadata=fixture();current=current_delivery(adapter,'slack','C123',metadata)
    if change=='withdraw':config['bindings']=[]
    elif change=='scope':config['bindings'][0]['scope']='TOTHER'
    elif change=='thread':config['bindings'][0]['thread']='1793000000.000001'
    elif change=='rights':config['bindings'][0]['capabilities']=['create']
    elif change=='identity':adapter._haos_native=SimpleNamespace(connector='bot',policy=adapter._haos_native.policy)
    else:adapter._haos_native.policy=lambda:GatewayPolicy(config)
    with pytest.raises(PermissionError):current()


@pytest.mark.parametrize('change',[{'haos_binding':{}},{'haos_scope':None},{'thread_id':True}])
def test_native_delivery_rejects_incomplete_or_coerced_owner_metadata(change):
    _config,adapter,metadata=fixture()
    with pytest.raises(PermissionError):current_delivery(adapter,'slack','C123',{**metadata,**change})
