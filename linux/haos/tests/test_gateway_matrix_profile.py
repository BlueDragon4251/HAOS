from copy import deepcopy
import pytest

from haos.gateway_matrix_profile import credentials


def valid():
    return {'token':'disposable-local-token','homeserver':'https://MATRIX.example.org:443/',
        'user_id':'@owner:example.org','device_id':'OWNER_DEVICE'}


def test_matrix_profile_credentials_are_copied_and_canonicalized():
    source=valid();previous=deepcopy(source);actual=credentials(source)
    assert source==previous and actual is not source
    assert actual['homeserver']=='https://matrix.example.org'


@pytest.mark.parametrize('change',[{'homeserver':'http://matrix.example.org'},
    {'homeserver':'https://secret@matrix.example.org'},{'homeserver':'https://matrix.example.org?token=x'},
    {'token':''},{'token':'token\nheader'},{'token':'x'*8193},{'user_id':'owner'},{'user_id':'@owner'},
    {'device_id':'*'},{'device_id':''},{'recovery_key':''},{'extra':{'allowed_users':'*'}},
    {'password':'implicit-new-device'},{'device_id':'DEVICE\x7f'}])
def test_matrix_profile_rejects_ambiguous_identity_credentials_or_native_overrides(change):
    source=valid();source.update(change)
    with pytest.raises(ValueError):credentials(source)


@pytest.mark.parametrize('field',['token','homeserver','user_id','device_id'])
def test_matrix_profile_requires_explicit_identity_fields(field):
    source=valid();del source[field]
    with pytest.raises(ValueError):credentials(source)
