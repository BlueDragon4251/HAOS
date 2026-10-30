"""Public publication and factory cannot bypass app or publisher authority."""
from copy import deepcopy
import json

import pytest

from haos.gateway import GatewayPolicy,digest
from haos.gateway_google_chat import credentials,scope
from haos.gateway_publication import validate_snapshot
from haos.gateway_runtime import build_adapter,credential_redactor
from haos.google_chat_account_setup import public
from test_gateway_google_chat import account,binding


def publication():
    value=account();value['inbound']['trust_topic_publishers']=True
    return {'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding()]},{'connectors':{'google':value}}


def test_public_policy_and_matched_snapshot_admit_only_explicit_account_and_publisher_trust():
    policy,private=publication();validate_snapshot(policy,private)
    assert GatewayPolicy(policy).bindings['owner']['scope']==scope(private['connectors']['google'])
    assert public(private['connectors']['google'])['inbound']['trust_topic_publishers'] is True
    assert private['connectors']['google']['service_account']['private_key'] not in str(public(private['connectors']['google']))


@pytest.mark.parametrize('value',[None,False,0,1,'true',[],{}])
def test_public_pubsub_cannot_silently_authorize_all_topic_publishers(value):
    policy,private=publication()
    if value is None:private['connectors']['google']['inbound'].pop('trust_topic_publishers')
    else:private['connectors']['google']['inbound']['trust_topic_publishers']=value
    with pytest.raises((ValueError,PermissionError)):validate_snapshot(policy,private)


@pytest.mark.parametrize('case',['duplicate-app','foreign-scope','self-bot','thread-overlap','cross-space','excess-spaces'])
def test_public_google_snapshot_refuses_duplicate_apps_ambiguous_grants_and_unbounded_spaces(case):
    policy,private=publication();row=policy['bindings'][0]
    if case=='duplicate-app':
        policy['connectors'].append({'id':'second','platform':'google_chat'});private['connectors']['second']=deepcopy(private['connectors']['google'])
        private['connectors']['second']['service_account']['private_key_id']='b'*40
    elif case=='foreign-scope':row['scope']='google-chat:'+'f'*64
    elif case=='self-bot':row['sender']='users/999'
    elif case=='thread-overlap':policy['bindings'].append({**row,'id':'whole-space','thread':'','all_threads':True})
    elif case=='cross-space':row['thread']='spaces/another/threads/thread1'
    else:policy['bindings']=[{**row,'id':'owner'+str(i),'chat':'spaces/space'+str(i),'thread':''} for i in range(33)]
    with pytest.raises(ValueError):validate_snapshot(policy,private)


def test_twenty_two_connectors_fit_bounded_policy_and_unknown_plugins_remain_refused():
    config={'version':1,'connectors':[{'id':'gateway'+str(i),'platform':'telegram'} for i in range(32)],'bindings':[]}
    assert len(GatewayPolicy(config).connectors)==32
    with pytest.raises(ValueError):GatewayPolicy({**config,'connectors':config['connectors']+[{'id':'extra','platform':'telegram'}]})
    config['connectors'][0]['platform']='arbitrary-plugin'
    with pytest.raises(ValueError):GatewayPolicy(config)


@pytest.mark.parametrize('context',[None,{}, {'parent':'/tmp','connector':'google','policy':None,'inbox':None,'plugin':True}])
def test_google_factory_requires_exact_private_context_before_loading_optional_runtime(context):
    with pytest.raises(PermissionError):build_adapter('google_chat',account(),google_chat_context=context)


def test_google_keys_and_nested_escaped_aliases_are_redacted_before_logging():
    policy,private=publication();key=private['connectors']['google']['service_account']['private_key']
    redactor=credential_redactor(private,GatewayPolicy(policy))
    aliases=[key,json.dumps(key)[1:-1],json.dumps(json.dumps(key)[1:-1])[1:-1],repr(key)[1:-1]]
    assert all(redactor.text(value)!=value for value in aliases)


def test_pubsub_owner_consent_does_not_change_stable_app_identity_but_changes_full_credential_fence():
    previous=account();changed=deepcopy(previous);changed['inbound']['trust_topic_publishers']=True
    assert credentials(changed)==changed and scope(previous)==scope(changed) and digest(previous)!=digest(changed)


@pytest.mark.parametrize('case',['publication','binding','connector','relabelled-empty'])
def test_public_output_policy_witness_refuses_mutated_or_relabelled_policy_objects(case):
    from haos.gateway_google_chat import checked_policy
    config,_=publication();selected=GatewayPolicy(config);assert checked_policy(selected) is selected
    if case=='publication':selected.publication='f'*64
    elif case=='binding':selected.bindings['owner']['allow_media']=True
    elif case=='connector':selected.connectors['google']['platform']='arbitrary-plugin'
    else:
        empty=GatewayPolicy({'version':1,'connectors':[],'bindings':[]})
        empty.connectors=selected.connectors;empty.bindings=selected.bindings;selected=empty
    with pytest.raises(PermissionError):checked_policy(selected)
