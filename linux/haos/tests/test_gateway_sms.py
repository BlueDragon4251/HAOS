import copy
from urllib.parse import urlencode
import pytest

from haos.gateway_sms import PreparedSMSPolicy,credentials,envelope,form,scope,validate_binding


def values():return {'account_sid':'AC'+'a'*32,'from_number':'+12025550100'}


def message():return {'AccountSid':'AC'+'a'*32,'MessageSid':'SM'+'d'*32,'From':'+12025550101','To':'+12025550100','Body':'  a real SMS goal  ','NumMedia':'0'}


def config():
    return {'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{'id':'owner','connector':'sms','sender':'+12025550101',
        'chat':'+12025550101','scope':scope(values()),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'c'*64,'since':1}]}


def test_prepared_sms_is_not_automatically_public_and_requires_exact_phone_scope():
    from haos.gateway import GatewayPolicy
    with pytest.raises(ValueError):GatewayPolicy(config())
    policy=PreparedSMSPolicy(config());source=envelope(message(),values())
    assert source['text']=='a real SMS goal' and source['scope']==scope(values())
    assert policy.authorize('sms',source)['id']=='owner'
    with pytest.raises(PermissionError):policy.authorize('sms',{**source,'sender':'+12025550199'})


@pytest.mark.parametrize('changes',[{'sender':'anonymous'},{'chat':'+12025550199'},{'scope':'any'},{'thread':'forged'},
    {'sender':'+12025550100','chat':'+12025550100'},{'since':None},{'generation':None}])
def test_sms_rejects_display_names_changed_recipient_threads_and_missing_epochs(changes):
    c=config();c['bindings'][0].update(changes)
    with pytest.raises(ValueError):PreparedSMSPolicy(c)


@pytest.mark.parametrize('raw',[b'From=one&From=two',b'Body=%ZZ',b'Body=%ff',b'Body=%f',b'no-equals',b'=missing-name',
    b'Body=x&bad.key=y',b'Body=x&'+b'a='*33000,b'Body='+b'x'*65536])
def test_ambiguous_or_unbounded_sms_forms_are_refused_before_optional_sdk_import(raw):
    with pytest.raises((ValueError,UnicodeError)):form(raw)


def test_sms_form_preserves_signed_unicode_and_literal_plus():
    original=message();original['Body']='Grüße + 😀'
    assert form(urlencode(original).encode())==original


@pytest.mark.parametrize('change',[{'AccountSid':'AC'+'f'*32},{'MessageSid':'../private'},{'From':'display name'},
    {'To':'+12025550199'},{'Body':''},{'Body':'x'*1601},{'NumMedia':'1'},{'MediaUrl0':'http://127.0.0.1/private'}])
def test_unreviewed_sms_identity_text_or_media_cannot_become_a_mission(change):
    item=message();item.update(change)
    with pytest.raises(ValueError):envelope(item,values())


@pytest.mark.parametrize('change',[{'account_sid':'AC../private'},{'auth_token':'bad'},{'from_number':'alice'},
    {'port':True},{'port':443},{'unexpected':'field'}])
def test_invalid_private_sms_settings_fail_before_optional_tls_or_sdk_work(change):
    value={**values(),'auth_token':'b'*32,'port':8647,'tls':{}};value.update(change)
    with pytest.raises(ValueError):credentials(value)
