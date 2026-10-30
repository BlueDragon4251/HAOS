"""Private Owner pipe never returns arbitrary SDK/private payloads."""
import argparse
import copy

import pytest

from test_gateway_photon_admission import source, custody, retain
from test_gateway_photon_recovery import request, retired
from test_gateway_photon_status import sample
from haos.gateway_photon_recovery import sources
from haos.photon_owner_process import params, response
from haos.photon_owner_cli import arguments


def test_actual_original_inventory_has_closed_owner_response_and_exact_selected_profile(source, custody):
    retain(source, custody); chosen = request(source, custody, retired(source))
    result = sources(custody[0], retired(source), chosen['profile'], lambda: None)
    assert response(result, 'sources', chosen) == result
    changed = copy.deepcopy(result); changed['sources'][0]['private_payload'] = 'must-not-return'
    with pytest.raises(ValueError): response(changed, 'sources', chosen)
    changed = copy.deepcopy(result); changed['sources'][0]['stored_bytes'] += 1
    with pytest.raises(ValueError): response(changed, 'sources', chosen)
    with pytest.raises(ValueError): response(result, 'sources', {**chosen, 'profile': 'photon-' + 'f' * 64})


@pytest.mark.parametrize('value', [{'error': 'private vendor response'}, {'error': []}, {'error': 'authority-refused', 'traceback': 'private'},
    {'profiles': [{}], 'history_truncated': False, 'network_requested': False, 'private_bytes_returned': False}])
def test_unbounded_or_private_owner_response_is_refused(value):
    with pytest.raises(ValueError): response(value, 'profiles', {})


def test_status_handoff_never_returns_active_authority_and_matches_original_selector():
    value = sample(); chosen = {key: value[key] for key in ['connector', 'credential_scope', 'account_scope']}
    result = {'result': value, 'active_authorization_returned': False}
    assert response(result, 'status', chosen) == result
    with pytest.raises(ValueError): response({**result, 'active_authorization_returned': True}, 'status', chosen)
    with pytest.raises(ValueError): response(result, 'status', {**chosen, 'credential_scope': 'c' * 64})
    with pytest.raises(ValueError): params('status', {**chosen, 'project_secret': 'must-not-handoff'}, 1000)


@pytest.mark.parametrize('change', [{'confirmed': False}, {'owner_uid': 0}, {'owner_uid': True}, {'note_sha256': 'private note'}, {'credentials': {}}])
def test_disposal_request_matches_authenticated_parent_owner_and_has_no_credentials(change):
    chosen = {'profile': 'photon-' + 'c' * 64, 'id': 'a' * 64, 'snapshot_sha256': 'b' * 64,
        'owner_uid': 1000, 'note_sha256': 'd' * 64, 'confirmed': True}
    assert params('purge-source', chosen, 1000) == chosen
    with pytest.raises(PermissionError): params('purge-source', {**chosen, **change}, 1000)


def test_nested_cli_parser_preserves_authenticated_owner_gateway_dispatch():
    parser = argparse.ArgumentParser(); parser.set_defaults(action='gateway')
    arguments(parser.add_subparsers(dest='gateway_action', required=True))
    value = parser.parse_args(['photon-recovery', 'status', '--connector', 'phone'])
    assert (value.action, value.gateway_action, value.photon_action, value.connector) == ('gateway', 'photon-recovery', 'status', 'phone')
