"""Owner form validation and delegation; kernel authority has separate UID probes."""
import pytest
from haos import initial_setup,gateway_setup


@pytest.fixture
def calls(monkeypatch):
    events=[]
    monkeypatch.setattr(initial_setup.os,'geteuid',lambda:0)
    monkeypatch.setattr(initial_setup,'quiesce_for_setup',lambda **kw:events.append(('stop',kw)))
    monkeypatch.setattr(gateway_setup,'owner_gateway',lambda args:events.append(('owner',vars(args))))
    return events


def test_inspected_mailbox_decision_keeps_exact_snapshot_and_stops_before_delegate(calls):
    row={'identity':'a'*64,'snapshot_sha256':'b'*64,'active':True,'status':'uid-validity-changed'}
    initial_setup.recover_email_gateway(row,'recover-email-mailbox','Inspected server reset',True)
    assert calls==[('stop',{'gateway_only':True}),('owner',{'gateway_action':'recover-email-mailbox',
        'identity':'a'*64,'snapshot_sha256':'b'*64,'note':'Inspected server reset','confirm_inspected':True})]


@pytest.mark.parametrize('change',[{'active':False},{'status':'ready'},{'identity':'../owner'},{'snapshot_sha256':'bad'}])
def test_mailbox_form_refuses_stale_or_uninspected_selection_before_stopping(calls,change):
    row={'identity':'a'*64,'snapshot_sha256':'b'*64,'active':True,'status':'uid-next-regressed',**change}
    with pytest.raises(ValueError):initial_setup.recover_email_gateway(row,'recover-email-mailbox','inspected',True)
    assert calls==[]


def test_source_disposal_requires_terminal_selection_and_opaque_profile(calls):
    row={'id':'c'*64,'snapshot_sha256':'d'*64,'purge_allowed':False}
    with pytest.raises(ValueError):initial_setup.recover_email_gateway(row,'purge-email-source','inspected',True,profile='email-'+'a'*64)
    row['purge_allowed']=True
    with pytest.raises(ValueError):initial_setup.recover_email_gateway(row,'purge-email-source','inspected',True,profile='/var/lib/owner')
    with pytest.raises(ValueError):initial_setup.recover_email_gateway(row,'purge-email-source','inspected',profile='email-'+'a'*64)
    assert calls==[]
    initial_setup.recover_email_gateway(row,'purge-email-source','inspected',True,profile='email-'+'a'*64)
    assert calls[-1][1]['id']=='c'*64 and calls[-1][1]['profile']=='email-'+'a'*64


def test_uncertain_smtp_permission_requires_separate_independent_non_delivery_confirmation(calls):
    row={'connector':'email','delivery_id':'a'*64,'attempt':1,'state':'uncertain','snapshot_sha256':'b'*64}
    with pytest.raises(ValueError):initial_setup.recover_email_gateway(row,'approve-email-retry','inspected',True)
    for patch in [{'state':'confirmed'},{'attempt':True},{'attempt':5},{'connector':'../other'}]:
        with pytest.raises(ValueError):initial_setup.recover_email_gateway({**row,**patch},'approve-email-retry','inspected',True,confirmed_not_delivered=True)
    assert calls==[]
    initial_setup.recover_email_gateway(row,'approve-email-retry','independently checked',True,confirmed_not_delivered=True)
    assert calls[-1][1]['confirm_not_delivered'] is True
    assert calls[-1][1]['gateway_action']=='approve-email-retry'


def test_source_inventory_does_not_accept_caller_paths(calls):
    with pytest.raises(ValueError):initial_setup.email_gateway_sources('/tmp/owner.db')
    assert calls==[]
    initial_setup.email_gateway_sources()
    assert calls[-1]==('owner',{'gateway_action':'email-sources','profile':None})


def test_receiving_server_custody_must_be_explicit_before_account_configuration(calls):
    with pytest.raises(PermissionError):initial_setup.configure_email_gateway('email',{})
    assert calls==[]


def test_email_owner_pairing_derives_saved_mailbox_and_creates_fresh_timed_grant(calls,monkeypatch):
    from copy import deepcopy
    from haos import owner
    from test_gateway_email_publication import fixture
    policy,credentials=fixture();policy['bindings']=[];saved=[]
    monkeypatch.setattr(gateway_setup,'load',lambda:(deepcopy(policy),deepcopy(credentials)))
    monkeypatch.setattr(gateway_setup,'persist',lambda p,c:saved.append((p,c)))
    monkeypatch.setattr(owner,'audit',lambda *args:None)
    with pytest.raises(ValueError):initial_setup.pair_gateway_sender('owner','email-main','owner@example.invalid','other@example.invalid','personal')
    with pytest.raises(ValueError):initial_setup.pair_gateway_sender('owner','email-main','owner@example.invalid','owner@example.invalid','personal',scope='mailbox:'+'b'*64)
    with pytest.raises(ValueError):initial_setup.pair_gateway_sender('owner','email-main','haos@example.invalid','haos@example.invalid','personal')
    assert calls==[] and saved==[]
    initial_setup.pair_gateway_sender('owner','email-main','owner@example.invalid','owner@example.invalid','personal',thread='<root@example.invalid>',allow_media=True,allow_outbound_media=True)
    first=saved[-1][0]['bindings'][0]
    assert len(first['generation'])==64 and type(first['since']) is int and first['since']>123
    assert first['scope'].startswith('mailbox:') and first['allow_media'] is True and first['allow_outbound_media'] is True
    assert first['allow_voice'] is False and first['allow_video'] is False
    initial_setup.pair_gateway_sender('owner','email-main','owner@example.invalid','owner@example.invalid','personal')
    assert saved[-1][0]['bindings'][0]['generation']!=first['generation']
