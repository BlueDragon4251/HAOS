import base64
from copy import deepcopy
import pytest
from haos.gateway_publication import validate_snapshot


def fixture():
    key=base64.b64encode(b'x'*32).decode().rstrip('=')
    policy={'version':1,'connectors':[{'id':'matrix-main','platform':'matrix'}],'bindings':[
        {'id':'phone','connector':'matrix-main','sender':'@owner:example.org','chat':'!room:example.org','scope':'','thread':'',
         'identity':'principal','capabilities':['create','read'],'matrix_devices':[{'device_id':'PHONE','ed25519':key,'curve25519':key}],
         'allow_plaintext':False,'require_mention':True}]}
    secret={'connectors':{'matrix-main':{'token':'disposable-private-token','homeserver':'https://matrix.example.org',
        'user_id':'@haos:example.org','device_id':'HAOS'}}}
    return policy,secret


def test_matrix_publication_accepts_complete_private_identity_and_explicit_device_grants():
    policy,secret=fixture();before=deepcopy(secret)
    validate_snapshot(policy,secret);assert secret==before


@pytest.mark.parametrize('field',['homeserver','user_id','device_id'])
def test_matrix_publication_refuses_token_without_complete_identity(field):
    policy,secret=fixture();del secret['connectors']['matrix-main'][field]
    with pytest.raises(ValueError):validate_snapshot(policy,secret)


@pytest.mark.parametrize('change',[{'extra':{'e2ee_mode':'off'}},{'homeserver':'https://MATRIX.example.org:443/'},
    {'device_id':'*'},{'homeserver':'http://matrix.example.org'}])
def test_matrix_publication_cannot_override_private_runtime_guards(change):
    policy,secret=fixture();secret['connectors']['matrix-main'].update(change)
    with pytest.raises(ValueError):validate_snapshot(policy,secret)


def test_matrix_service_account_cannot_pair_itself_as_owner_input():
    policy,secret=fixture();policy['bindings'][0]['sender']='@haos:example.org'
    with pytest.raises(ValueError):validate_snapshot(policy,secret)
