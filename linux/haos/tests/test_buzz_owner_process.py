"""Finite owner responses cannot claim writes, live acceptance or new authority."""
import pytest

from haos.buzz_owner_process import response
from haos.gateway_buzz import scope

ACCOUNT={'relay_url':'https://buzz.fixture.invalid','public_key':'a'*64,'channels':['01234567-89ab-4cde-8012-3456789abcde']}


def checked():return {'runtime_ready':True,'identity_verified':True,'read_query_succeeded':True,'account_scope':scope(ACCOUNT),
    'channels_checked':1,'message_sent':False,'mission_created':False,'grants_changed':False,'external_acceptance_verified':False}


@pytest.mark.parametrize('change',[{'message_sent':True},{'mission_created':True},{'grants_changed':True},
    {'external_acceptance_verified':True},{'runtime_ready':1},{'channels_checked':True},{'channels_checked':2},
    {'account_scope':'buzz:'+'b'*64},{'private_key':'opaque-private-value'},{'identity_verified':False}])
def test_owner_account_response_cannot_upgrade_local_read_to_external_acceptance_or_mutate_grants(change):
    with pytest.raises(ValueError):response({**checked(),**change},'account',ACCOUNT)


def test_no_send_account_result_and_only_closed_diagnostics_are_accepted_without_optional_SDK():
    assert response(checked(),'account',ACCOUNT)==checked()
    assert response({'error':'authentication-refused'},'account',ACCOUNT)=={'error':'authentication-refused'}
    for value in [{'error':'relay reflected private data'},{'error':[]},{'error':'storage-unavailable','detail':'opaque'}]:
        with pytest.raises(ValueError):response(value,'account',ACCOUNT)


@pytest.mark.parametrize('change',[{'network_requested':True},{'private_bytes_returned':True},
    {'history_truncated':1},{'outputs':[{}]},{'outputs':'private bytes'},{'content':'raw retained private input'}])
def test_owner_output_inventory_cannot_return_arbitrary_journal_bytes_or_untyped_entries(change):
    value={'outputs':[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
    with pytest.raises(ValueError):response({**value,**change},'outputs',ACCOUNT)
