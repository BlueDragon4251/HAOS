"""Recorded metadata cannot masquerade as live status or carry credentials."""
import pytest

from haos.gateway_photon_status import checked, selector


def sample():
    return {'connector': 'phone', 'credential_scope': 'a' * 64, 'account_scope': 'photon:' + 'b' * 64,
        'status': 'upstream-observed', 'updated_at': 1793430000, 'next_attempt': 1793430180,
        'observed_only': True, 'live_transport_verified': False, 'network_requested': False, 'private_credentials_returned': False}


def test_exact_recorded_status_never_grants_authority_or_claims_live_verification():
    value = sample(); request = {key: value[key] for key in ['connector', 'credential_scope', 'account_scope']}
    assert checked(value, request) == value
    assert checked({**value, 'status': 'not-started', 'updated_at': None})['next_attempt'] == value['next_attempt']
    for key, change in [('connector', 'other'), ('credential_scope', 'c' * 64), ('account_scope', 'photon:' + 'c' * 64)]:
        with pytest.raises(ValueError): checked(value, {**request, key: change})
    with pytest.raises(ValueError): selector({**request, 'project_secret': 'must-not-accept'})


@pytest.mark.parametrize('change', [
    {'status': []}, {'status': 'private vendor response'}, {'status': 'connected'}, {'updated_at': None},
    {'updated_at': True}, {'updated_at': float('nan')}, {'next_attempt': float('inf')}, {'next_attempt': -1},
    {'next_attempt': True}, {'next_attempt': 253402300800}, {'network_requested': True},
    {'private_credentials_returned': True}, {'live_transport_verified': True}, {'observed_only': False},
    {'token': 'must-not-return'}, {'credential_scope': 'private-value'}, {'account_scope': 'photon:wrong'}, {'connector': '../profile'},
])
def test_private_unbounded_or_falsely_verified_metadata_is_refused(change):
    with pytest.raises(ValueError): checked({**sample(), **change})
