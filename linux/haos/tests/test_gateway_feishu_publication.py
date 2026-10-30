"""Public Feishu policy/account contracts; native transport proofs are separate."""
from copy import deepcopy
import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_publication import validate_snapshot
from haos.gateway_runtime import build_adapter
from test_gateway_feishu import account,binding


def fixture():return {'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding()]},{'connectors':{'feishu':account()}}


def test_public_snapshot_requires_the_exact_independent_native_route_and_private_account():
    policy,private=fixture();validate_snapshot(policy,private)
    assert GatewayPolicy(policy).bindings['owner']==binding()
    with pytest.raises(ValueError):build_adapter('feishu',account())


@pytest.mark.parametrize('change',[{'scope':'feishu:'+'a'*64},{'sender':'ou_'+'a'*32},
    {'sender':'display name'},{'chat':'*'},{'thread':'om_'+'d'*32},{'generation':None},{'since':True}])
def test_public_snapshot_refuses_ambiguous_stale_or_self_authorized_routes(change):
    policy,private=fixture();policy['bindings'][0].update(change)
    with pytest.raises(ValueError):validate_snapshot(policy,private)


@pytest.mark.parametrize('change',[{'extra':{'plugin':'external'}},{'domain':'https://other.invalid'},
    {'verification_token':'unused-private-fixture'},{'app_secret':'short'}])
def test_public_snapshot_refuses_plugin_fields_arbitrary_urls_unused_secrets_and_invalid_credentials(change):
    policy,private=fixture();private['connectors']['feishu'].update(change)
    with pytest.raises(ValueError):validate_snapshot(policy,private)
