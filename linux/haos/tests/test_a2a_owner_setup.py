"""Prepared owner publication, private-material omission and closed inventories."""

import pytest

from haos.a2a_owner_process import cursor_token,cursor_value,response
from haos.a2a_owner_setup import public
from haos.gateway import GatewayPolicy
from haos.gateway_a2a import scope
from haos.gateway_publication import owner_policy


@pytest.mark.parametrize('value',['../owner','=',False,None,'WzEsMiwzLDRd','W3RydWUsMCwwXQ','WzAsMTcsMF0','WzAsMCw2NTUzN10'])
def test_owner_inventory_cursor_cannot_route_paths_or_expand_its_page_bounds(value):
    with pytest.raises(ValueError):cursor_value(value)


def test_owner_inventory_cursor_round_trips_only_canonical_bounded_numeric_positions():
    assert cursor_value('')==[0,0,0]
    assert cursor_value(cursor_token([65536,16,65536]))==[65536,16,65536]


@pytest.fixture
def account():
    # Public-field projection has no TLS/runtime operation. Actual cryptographic
    # snapshot checks run in the installed-UID process fixture with real PEMs.
    return {'peer_tokens':{'alice':'private_owner_peer_fixture_'+'a'*32},'port':8448,'agent_name':'HAOS',
        'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':'private fixture certificate bytes',
            'private_key':'private fixture TLS key bytes','bind_host':'127.0.0.1','public_listener':False}}


def test_prepared_owner_publication_does_not_activate_a2a_in_public_runtime_registry(account):
    policy={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[]}
    assert owner_policy(policy).connectors['a2a']['platform']=='a2a'
    with pytest.raises(ValueError):GatewayPolicy(policy)


def test_prepared_owner_callback_flag_requires_explicit_read_permission(account):
    binding={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-owner','scope':scope(account,'alice'),'thread':'',
        'identity':'personal','capabilities':['create'],'generation':'a'*64,'since':1,'allow_callback':True}
    policy={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding]}
    with pytest.raises(ValueError):owner_policy(policy)
    binding['capabilities'].append('read');assert owner_policy(policy).bindings['owner']['allow_callback'] is True


def test_owner_metadata_omits_peer_signing_and_tls_keys(account):
    account['callbacks']={'alice':{'url':'https://peer.fixture.invalid/callback','secret':'private_owner_signing_fixture_'+'b'*32}}
    value=public(account)
    assert value['peers']==[{'name':'alice','saved_token':True,'download_origins':[],
        'callback_url':'https://peer.fixture.invalid/callback','saved_callback_secret':True}]
    assert all(secret not in str(value) for secret in [account['peer_tokens']['alice'],account['callbacks']['alice']['secret'],account['tls']['private_key']])


def test_owner_worker_result_never_claims_network_reachability_or_message_delivery():
    result={'runtime_ready':True,'tls_material_valid':True,'listener_bindable':True,'external_reachability_verified':False,
        'message_sent':False,'mission_created':False}
    assert response(result,'inspect')==result
    for field in ['external_reachability_verified','message_sent','mission_created']:
        with pytest.raises(ValueError):response({**result,field:True},'inspect')
    with pytest.raises(ValueError):response({'tasks':[],'has_more':True,'cursor':'','message_sent':False,'mission_created':False},'sources')
