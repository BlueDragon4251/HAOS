from copy import deepcopy
import base64
import time
import pytest
from haos.gateway import GatewayPolicy,digest
from haos.gateway_matrix_policy import PreparedMatrixPolicy,authorize_original,snapshot


def fixture():
    key=base64.b64encode(b'x'*32).decode().rstrip('=')
    config={'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
        {'id':'paired','connector':'bot','sender':'@owner:example.org','chat':'!private:example.org','scope':'','thread':'',
         'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-1000,
         'allow_plaintext':False,'require_mention':True,'matrix_devices':[{'device_id':'PHONE','ed25519':key,'curve25519':key}]}]}
    envelope={'platform':'matrix','sender':'@owner:example.org','chat':'!private:example.org','scope':'','thread':'',
              'message_id':'$original','is_bot':False,'text':'native text'}
    crypto={'sender':envelope['sender'],'room':envelope['chat'],'event_id':'$original','device_id':'PHONE','ed25519':key,'curve25519':key}
    return config,envelope,crypto


def test_prepared_matrix_class_cannot_be_selected_by_installed_controller_policy():
    config,_,_=fixture()
    with pytest.raises(ValueError):GatewayPolicy(config)
    assert PreparedMatrixPolicy(config).connectors['bot']['platform']=='matrix'


@pytest.mark.parametrize('change',[{'sender':'foreign'},{'chat':'#alias:example.org'},{'scope':'*'},
    {'thread':'not-event'},{'allow_plaintext':'true'},{'require_mention':1},{'matrix_devices':[]},
    {'matrix_devices':[{'device_id':'PHONE','ed25519':'bad','curve25519':'bad'}]}])
def test_invalid_route_or_implicit_device_policy_is_refused(change):
    config,_,_=fixture();config['bindings'][0].update(change)
    with pytest.raises(ValueError):PreparedMatrixPolicy(config)


@pytest.mark.parametrize('field',['sender','chat','scope','thread','is_bot','platform'])
def test_prepared_matrix_uses_shared_exact_haos_source_authorization(field):
    config,envelope,crypto=fixture();policy=PreparedMatrixPolicy(config)
    envelope[field]=True if field=='is_bot' else 'foreign'
    with pytest.raises(PermissionError):authorize_original(policy,'bot',envelope,int(time.time()*1000),snapshot(policy,'bot'),crypto)


@pytest.mark.parametrize('field',['device_id','ed25519','curve25519','sender','room','event_id'])
def test_device_and_crypto_envelope_are_all_bound(field):
    config,envelope,crypto=fixture();policy=PreparedMatrixPolicy(config);crypto[field]='foreign'
    with pytest.raises(PermissionError):authorize_original(policy,'bot',envelope,int(time.time()*1000),snapshot(policy,'bot'),crypto)


def test_raw_authority_snapshot_never_renews_or_grants_an_old_epoch():
    config,envelope,crypto=fixture();before=PreparedMatrixPolicy(deepcopy(config));captured=snapshot(before,'bot')
    config['bindings'][0]['generation']='b'*64
    with pytest.raises(PermissionError):authorize_original(PreparedMatrixPolicy(config),'bot',envelope,int(time.time()*1000),captured,crypto)
    assert digest(config['bindings'][0]) not in captured['binding_digests']


def test_plaintext_needs_explicit_owner_consent_and_original_grant_time():
    config,envelope,_=fixture();policy=PreparedMatrixPolicy(config)
    with pytest.raises(PermissionError):authorize_original(policy,'bot',envelope,int(time.time()*1000),snapshot(policy,'bot'),None)
    config['bindings'][0].update(allow_plaintext=True,matrix_devices=[])
    policy=PreparedMatrixPolicy(config)
    assert authorize_original(policy,'bot',envelope,int(time.time()*1000),snapshot(policy,'bot'),None)['id']=='paired'
    with pytest.raises(PermissionError):authorize_original(policy,'bot',envelope,config['bindings'][0]['since'],snapshot(policy,'bot'),None)


def test_matrix_device_wildcard_never_means_explicit_owner_approval():
    config,_,_=fixture();config['bindings'][0]['matrix_devices'][0]['device_id']='*'
    with pytest.raises(ValueError):PreparedMatrixPolicy(config)
