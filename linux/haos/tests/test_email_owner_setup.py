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
