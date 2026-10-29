"""Closed upload receipt and intent contracts; actual SDK/UID proofs are separate."""
import pytest
from haos.gateway_feishu_upload import response
from haos.gateway_feishu_upload_http import target


def exact():return {'kind':'file','name':'result-0.bin','size':1,'sha256':'a'*64,'file_type':'stream','duration_ms':0}


@pytest.mark.parametrize('change',[{'kind':'other'},{'name':'/private/file.bin'},{'name':'../result-0.bin'},
    {'size':True},{'size':8*1024*1024+1},{'file_type':''},{'file_type':'external-client'},
    {'duration_ms':True},{'duration_ms':3600001},{'url':'https://other.invalid'}])
def test_upload_target_refuses_paths_unreviewed_options_and_ambiguous_values(change):
    with pytest.raises((ValueError,PermissionError)):target({**exact(),**change})


def test_upload_receipt_distinguishes_acceptance_from_uncertainty_and_native_refusal():
    assert response({'state':'confirmed','kind':'file','key':'file_v3_0000000000000000'},exact())['state']=='confirmed'
    assert response({'state':'uncertain'},exact())=={'state':'uncertain'}
    assert response({'state':'rejected','error':'native-refused'},exact())['error']=='native-refused'


@pytest.mark.parametrize('result',[{'state':'confirmed','kind':'image','key':'img_v3_0000000000000000'},
    {'state':'confirmed','kind':'file','key':'1'},
    {'state':'confirmed','kind':'file','key':'file_v3_0000000000000000','message_delivered':True},
    {'state':'uncertain','retryable':True},{'state':'rejected','error':'raw unbounded SDK exception'},
    {},None])
def test_upload_never_promotes_ambiguous_or_extra_private_fields_to_delivery(result):
    with pytest.raises(ValueError):response(result,exact())



def test_private_gateway_logger_registers_feishu_credentials_without_poisoning_public_ids():
    from haos.gateway_runtime import credential_redactor
    from haos.gateway_feishu import PreparedFeishuPolicy
    from test_gateway_feishu import account
    value=account();policy=PreparedFeishuPolicy({'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[]})
    redactor=credential_redactor({'connectors':{'feishu':value}},policy)
    assert value['app_secret'] not in redactor.text(value['app_secret'])
    assert redactor.text(value['app_id'])==value['app_id'] and redactor.text('Goal 1')=='Goal 1'
