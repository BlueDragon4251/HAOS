"""Public email identity/publication contracts, without optional SDK or accounts."""
import base64
from copy import deepcopy
import pytest
from haos.gateway_publication import validate_snapshot
from haos.gateway import GatewayPolicy
from haos.gateway_runtime import credential_redactor,build_adapter
from haos.gateway_email import scope


def fixture():
    account={'address':'haos@example.invalid','password':'private-mail-fixture',
        'imap_host':'imap.example.invalid','imap_port':993,'imap_security':'tls',
        'smtp_host':'smtp.example.invalid','smtp_port':587,'smtp_security':'starttls','authserv_id':'mx.example.invalid'}
    policy={'version':1,'connectors':[{'id':'email-main','platform':'email'}],'bindings':[{
        'id':'owner','connector':'email-main','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope(account),'thread':'<root@example.invalid>','identity':'personal','capabilities':['create','read'],
        'generation':'a'*64,'since':123}]}
    return policy,{'connectors':{'email-main':account}}


def test_public_email_snapshot_accepts_only_canonical_private_account_and_exact_timed_grants():
    policy,credentials=fixture();original=deepcopy(credentials)
    validate_snapshot(policy,credentials)
    assert credentials==original and GatewayPolicy(policy).bindings['owner']['thread']=='<root@example.invalid>'


@pytest.mark.parametrize('field',['address','password','imap_host','imap_port','imap_security','smtp_host','smtp_port','smtp_security','authserv_id'])
def test_incomplete_mail_identity_is_refused_by_root_publication(field):
    policy,credentials=fixture();del credentials['connectors']['email-main'][field]
    with pytest.raises(ValueError):validate_snapshot(policy,credentials)


@pytest.mark.parametrize('change',[{'imap_security':'plain'},{'smtp_security':'plain'},{'smtp_port':True},
    {'imap_host':'https://imap.example.invalid'},{'extra':{'plugin':'unreviewed'}},{'password':'private\r\nsecret'}])
def test_public_mail_account_cannot_downgrade_tls_or_inject_plugins(change):
    policy,credentials=fixture();credentials['connectors']['email-main'].update(change)
    with pytest.raises(ValueError):validate_snapshot(policy,credentials)


@pytest.mark.parametrize('change',[{'sender':'haos@example.invalid','chat':'haos@example.invalid'},
    {'scope':'mailbox:'+'b'*64},{'chat':'other@example.invalid'},{'thread':'*'},{'generation':None},{'since':None}])
def test_public_mail_grants_cannot_move_mailboxes_recipients_or_missing_authority_epochs(change):
    policy,credentials=fixture();policy['bindings'][0].update(change)
    with pytest.raises(ValueError):validate_snapshot(policy,credentials)


def test_mail_password_and_native_auth_encodings_are_redacted_before_sdk_logging():
    policy,credentials=fixture();account=credentials['connectors']['email-main']
    redactor=credential_redactor(credentials,GatewayPolicy(policy))
    aliases=[account['password'],base64.b64encode(account['password'].encode()).decode(),
        base64.b64encode(('\0'+account['address']+'\0'+account['password']).encode()).decode()]
    for value in aliases:assert value not in redactor.text('server diagnostic '+value)


def test_email_factory_never_constructs_an_adapter_without_independent_private_profile_context():
    _,credentials=fixture()
    for context in [None,{}, {'parent':'/tmp/unapproved'}]:
        with pytest.raises(ValueError):build_adapter('email',credentials['connectors']['email-main'],email_context=context)
