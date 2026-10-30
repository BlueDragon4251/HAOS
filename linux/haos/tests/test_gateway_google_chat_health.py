"""Recorded status is bounded metadata, never a live connection or capability."""
from copy import deepcopy
import pytest

from haos.gateway_google_chat_health import checked,selector
from haos.google_chat_retired_process import response


def sample():return {'connector':'google','credential_scope':'a'*64,'account_scope':'google-chat:'+'b'*64,'status':'connected-pull',
    'updated_at':1793430000,'next_attempt':1793430180,'observed_only':True,'live_transport_verified':False,
    'network_requested':False,'private_credentials_returned':False}


def test_recorded_status_has_exact_original_account_selector_and_no_live_or_api_claim():
    value=sample();request={key:value[key] for key in ['connector','credential_scope','account_scope']}
    assert checked(value,request)==value
    assert response({'result':value,'active_authorization_returned':False},'status',request=request)['result']==value
    assert checked({**value,'status':'not-started','updated_at':None})['next_attempt']==value['next_attempt']
    with pytest.raises(ValueError):checked(value,{**request,'credential_scope':'c'*64})


@pytest.mark.parametrize('change',[{'status':[]},{'status':'arbitrary private traceback'},{'updated_at':None},{'updated_at':True},
    {'updated_at':float('nan')},{'next_attempt':float('inf')},{'next_attempt':-1},{'next_attempt':True},
    {'network_requested':True},{'private_credentials_returned':True},{'live_transport_verified':True},{'observed_only':False},
    {'token':'must-not-return'},{'credential_scope':'private-value'},{'account_scope':'google-chat:wrong'},{'connector':'../profile'}])
def test_status_projection_rejects_private_unbounded_or_falsely_verified_metadata(change):
    with pytest.raises(ValueError):checked({**sample(),**change})


def test_status_response_cannot_return_active_authority_or_foreign_connector_data():
    value={'result':sample(),'active_authorization_returned':True}
    with pytest.raises(ValueError):response(value,'status')
    value['active_authorization_returned']=False
    request={key:value['result'][key] for key in ['connector','credential_scope','account_scope']}
    with pytest.raises(ValueError):response(value,'status',request={**request,'connector':'another'})
    with pytest.raises(ValueError):selector({**request,'credentials':{'private_key':'must-not-accept'}})
