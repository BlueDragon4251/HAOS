from copy import deepcopy
import time
import pytest

from haos.gateway import digest
from haos.gateway_email import PreparedEmailPolicy,scope
from haos.gateway_email_process import smtp_response
from haos.gateway_email_smtp import specification,identity


def fixture():
    value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'imap.example.invalid','imap_port':993,
        'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':465,'smtp_security':'tls','authserv_id':'mx.example.invalid'}
    binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':scope(value),
        'thread':'<root@example.invalid>','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
    item={'binding_id':'owner','binding_digest':digest(binding),'delivery_id':'d'*64,'attempt':1,'source_id':'e'*64,
        'rfc_message_id':'<source@example.invalid>','root_message_id':binding['thread'],'subject':'Retained subject',
        'body':'A bounded actual reply. Grüße!','created_at':int(time.time()),'recipient':binding['chat']}
    return value,config,item


def test_exact_current_mail_reply_has_a_stable_message_identity_and_independent_copy():
    value,config,item=fixture();result=specification(value,PreparedEmailPolicy(config),'email',item)
    assert result==item and result is not item
    assert identity(value,item)==identity(value,deepcopy(item))
    assert identity(value,item)!=identity(value,{**item,'attempt':2})


@pytest.mark.parametrize('change',[{'recipient':'other@example.invalid'},{'root_message_id':''},{'attempt':True},
    {'attempt':6},{'delivery_id':'not-an-id'},{'source_id':'wrong'},{'binding_digest':'c'*64},
    {'rfc_message_id':'<bad@id>\r\nBcc: other@example.invalid'},{'subject':'bad\r\nBcc: other@example.invalid'},
    {'subject':'x'*1025},{'body':' '},{'body':'x'*32001},{'body':'bad\0body'},{'created_at':True},
    {'created_at':0},{'created_at':2**39},{'unknown':'plugin-field'}])
def test_unauthorized_or_unbounded_reply_is_refused_before_any_sdk_connection(change):
    value,config,item=fixture()
    with pytest.raises((ValueError,PermissionError)):specification(value,PreparedEmailPolicy(config),'email',{**item,**change})


@pytest.mark.parametrize('change',['revoked','read-removed','other-connector'])
def test_current_owner_authority_is_required_for_every_reply(change):
    value,config,item=fixture()
    if change=='revoked':config['bindings'][0]['generation']='c'*64
    elif change=='read-removed':
        config['bindings'][0]['capabilities']=['create'];item['binding_digest']=digest(config['bindings'][0])
    else:config['connectors'].append({'id':'other','platform':'email'})
    with pytest.raises(PermissionError):specification(value,PreparedEmailPolicy(config),'other' if change=='other-connector' else 'email',item)


def test_only_exact_message_acceptance_is_a_receipt_and_never_recipient_delivery():
    value,_config,item=fixture()
    receipt='smtp_accept_'+digest([identity(value,item),item['delivery_id'],item['attempt']])
    accepted={'accepted':True,'receipt':receipt,'recipient_receipt_verified':False}
    assert smtp_response(accepted,value,item)==accepted
    for changed in [{**accepted,'recipient_receipt_verified':True},{**accepted,'receipt':'smtp_accept_'+'0'*64},
            {**accepted,'accepted':1},{**accepted,'server_body':'private response'}]:
        with pytest.raises(ValueError):smtp_response(changed,value,item)
    assert smtp_response({'error':'smtp-temporary-refusal'},value,item)=={'error':'smtp-temporary-refusal'}
    with pytest.raises(ValueError):smtp_response({'error':'private server response'},value,item)


@pytest.mark.parametrize('field',['body','subject'])
def test_private_account_password_or_authentication_alias_never_enters_a_reply(field):
    import base64
    value,config,item=fixture()
    for secret in [value['password'],base64.b64encode(value['password'].encode()).decode(),
            base64.b64encode(('\0'+value['address']+'\0'+value['password']).encode()).decode()]:
        with pytest.raises(PermissionError):specification(value,PreparedEmailPolicy(config),'email',{**item,field:secret})


def test_long_valid_account_domain_cannot_expand_generated_message_id_past_its_contract():
    from haos.gateway_email import message_id,address
    value,_config,item=fixture();value['address']='haos@'+'.'.join(['a'*63]*3)+'.invalid'
    assert address(value['address'])==value['address']
    assert message_id(identity(value,item)) and len(identity(value,item))<=256
