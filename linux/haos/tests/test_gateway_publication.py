import copy

import pytest

from haos.gateway_publication import validate_snapshot


def snapshot():
    return ({'version': 1, 'publication': 'a'*64, 'connectors': [{'id': 'bot', 'platform': 'telegram'}], 'bindings': []},
        {'publication': 'a'*64, 'connectors': {'bot': {'token': 'fixture-private-credential'}}})


def test_gateway_startup_accepts_only_a_matched_policy_and_credential_snapshot():
    policy, credentials = snapshot()
    validate_snapshot(policy, credentials)
    old = copy.deepcopy(credentials); old['publication'] = 'b'*64
    with pytest.raises(PermissionError): validate_snapshot(policy, old)
    del old['publication']
    with pytest.raises(PermissionError): validate_snapshot(policy, old)
    legacy_policy = {key: value for key, value in policy.items() if key != 'publication'}
    validate_snapshot(legacy_policy, old)
    with pytest.raises(PermissionError): validate_snapshot(legacy_policy, credentials)


@pytest.mark.parametrize('change', ['missing-connector', 'extra-connector', 'short-token', 'whitespace', 'wrong-extra', 'oversized'])
def test_invalid_gateway_publication_cannot_be_installed(change):
    policy, credentials = snapshot()
    if change == 'missing-connector': credentials['connectors'] = {}
    elif change == 'extra-connector': credentials['connectors']['foreign'] = {'token': 'fixture-private-credential'}
    elif change == 'short-token': credentials['connectors']['bot']['token'] = 'short'
    elif change == 'whitespace': credentials['connectors']['bot']['token'] = 'fixture invalid token'
    elif change == 'wrong-extra': credentials['connectors']['bot']['extra'] = []
    else: credentials['connectors']['bot']['extra'] = {'value': 'x'*32768}
    with pytest.raises(ValueError): validate_snapshot(policy, credentials)
