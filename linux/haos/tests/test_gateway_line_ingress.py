import copy
import time

import pytest

from haos.gateway import GatewayPolicy
from haos.gateway_line_ingress import PreparedLINEPolicy,envelope,snapshot


def configuration():
    return {'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'C'+'b'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':1}]}


@pytest.mark.parametrize('change',[{'sender':'nickname'},{'chat':'group-name'},{'scope':''},{'thread':'thread'},
    {'generation':''},{'since':True},{'chat':'U'+'b'*32}])
def test_prepared_line_requires_exact_user_conversation_destination_and_owner_epoch(change):
    config=configuration();config['bindings'][0].update(change)
    with pytest.raises(ValueError):PreparedLINEPolicy(config)


def test_public_line_keeps_exact_destination_and_cross_connector_authority():
    config=configuration()
    assert snapshot(GatewayPolicy(config),'line','U'+'d'*32)['bindings']
    with pytest.raises(PermissionError):snapshot(PreparedLINEPolicy(config),'unknown','U'+'d'*32)
    assert snapshot(PreparedLINEPolicy(config),'line','U'+'d'*32)['bindings']


@pytest.mark.parametrize('change',[{'sender':'nickname'},{'chat':'group-name'},{'scope':''},{'thread':'thread'},
    {'chat':'U'+'b'*32}])
def test_public_line_cannot_bypass_native_route_validation(change):
    config=configuration();config['bindings'][0].update(change)
    with pytest.raises(ValueError):GatewayPolicy(config)


def test_public_line_publication_refuses_unverified_plain_listener_without_optional_sdk():
    from haos.gateway_publication import validate_snapshot
    config=configuration()
    private={'connectors':{'line':{'channel_secret':'a'*32,'channel_access_token':'private-publication-fixture',
        'destination':'U'+'d'*32,'port':8646}}}
    with pytest.raises(ValueError,match='verified HTTPS'):validate_snapshot(config,private)


@pytest.mark.parametrize('kind,prefix',[('user','U'),('group','C'),('room','R')])
def test_line_resolves_exact_signed_source_kind_without_falling_back_to_chat_as_user(kind,prefix):
    user='U'+'a'*32;source={'type':kind,'userId':user}
    if kind!='user':source[kind+'Id']=prefix+'b'*32
    event={'type':'message','mode':'active','timestamp':int(time.time()*1000),'webhookEventId':'01K8'+'A'*22,
        'source':source,'message':{'type':'text','id':'1234','text':'hello'}}
    decoded=envelope(event,'U'+'d'*32)
    assert decoded[0]['sender']==user and decoded[0]['chat']==(user if kind=='user' else prefix+'b'*32)
    bad=copy.deepcopy(event);del bad['source']['userId']
    assert envelope(bad,'U'+'d'*32) is None
