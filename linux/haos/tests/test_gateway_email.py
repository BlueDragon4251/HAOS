import pytest

from haos.gateway import GatewayPolicy
from haos.gateway_email import PreparedEmailPolicy,address,credentials,scope,validate_binding


def settings():return {'address':'haos@example.invalid','password':'private-email-fixture',
    'imap_host':'imap.example.invalid','imap_port':993,'imap_security':'tls',
    'smtp_host':'smtp.example.invalid','smtp_port':587,'smtp_security':'starttls','authserv_id':'mx.example.invalid'}


def policy():
    return {'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[{
        'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope(settings()),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}]}


def test_email_is_not_public_before_native_transport_media_and_owner_paths_are_connected():
    with pytest.raises(ValueError):GatewayPolicy(policy())
    assert PreparedEmailPolicy(policy()).bindings['owner']['scope']==scope(settings())
    assert credentials(settings())==settings()
    changed={**settings(),'imap_host':'other.example.invalid'}
    assert scope(changed)!=scope(settings())
    assert scope({**settings(),'password':'rotated-private-fixture'})==scope(settings())


@pytest.mark.parametrize('value',['Owner@example.invalid','owner@Example.invalid','owner@*.invalid','owner@example..invalid',
    'Display <owner@example.invalid>','owner@example.invalid\r\nBcc: other@example.invalid','@example.invalid',
    'owner','owner@domain.','owner@[127.0.0.1]','.owner@example.invalid','owner..name@example.invalid','ü@example.invalid'])
def test_email_sender_is_an_exact_address_without_display_names_wildcards_or_header_injection(value):
    with pytest.raises(ValueError):address(value)


@pytest.mark.parametrize('change',[{'imap_security':'plain'},{'smtp_security':'none'},{'imap_port':True},{'smtp_port':0},
    {'smtp_host':'https://smtp.example.invalid'},{'authserv_id':'*.example.invalid'},
    {'password':'private\r\nsecret'},{'unexpected':'plugin'},{'address':'haos@example.invalid\n'}])
def test_email_private_settings_fail_closed_without_importing_optional_hermes(change):
    with pytest.raises(ValueError):credentials({**settings(),**change})


@pytest.mark.parametrize('change',[{'chat':'other@example.invalid'},{'scope':'INBOX'},{'thread':'*'},
    {'thread':'<a@example.invalid>\nBcc: other@example.invalid'},{'thread':'<a@b@c>'},{'thread':'<a@@b>'},{'generation':None},{'since':None}])
def test_email_binding_rejects_changed_recipient_scope_thread_and_missing_epoch(change):
    binding={**policy()['bindings'][0],**change}
    with pytest.raises(ValueError):validate_binding(binding)


def test_email_root_thread_is_exact_and_bounded():
    binding={**policy()['bindings'][0],'thread':'<owner-thread@example.invalid>'}
    validate_binding(binding)


@pytest.mark.parametrize('change',[{'smtp_message_sent':True},{'uid_validity':True},{'uid_next':0},{'uid_next':2**32},
    {'unexpected':'private'},{'smtp_authenticated':False}])
def test_private_email_worker_cannot_claim_unbounded_or_side_effecting_probe_success(change):
    from haos.gateway_email_process import response
    value={'imap_authenticated':True,'smtp_authenticated':True,'uid_validity':77,'uid_next':3,'smtp_message_sent':False}
    with pytest.raises(ValueError):response({**value,**change})


@pytest.mark.parametrize('error',['private-provider-body',[],None,17])
def test_private_email_worker_diagnostics_are_finite_not_provider_error_bodies(error):
    from haos.gateway_email_process import response
    with pytest.raises(ValueError):response({'error':error})


def test_private_email_worker_accepts_only_typed_no_send_receipt_or_finite_diagnostic():
    from haos.gateway_email_process import response
    value={'imap_authenticated':True,'smtp_authenticated':True,'uid_validity':77,'uid_next':3,'smtp_message_sent':False}
    assert response(value)==value
    assert response({'error':'tls-refused'})=={'error':'tls-refused'}
