"""Exact independent callback approval and key separation without SDK imports."""
import pytest

from haos.gateway_a2a_callback_config import callbacks,destination


@pytest.mark.parametrize('url',['http://peer.fixture.invalid/callback','https://localhost/callback',
    'https://10.0.0.1/callback','https://169.254.169.254/latest','https://[::1]/callback',
    'https://peer.local/callback','https://peer.fixture.invalid/callback?token=private',
    'https://owner:password@peer.fixture.invalid/callback','https://peer.fixture.invalid/callback#fragment',
    'https://PEER.fixture.invalid/callback','https://peer.fixture.invalid:443/callback','https://peer.fixture.invalid',
    'https://peer.fixture.invalid\\@other.invalid/callback'])
def test_unapproved_transport_credential_local_alias_and_noncanonical_callback_destinations_are_refused(url):
    with pytest.raises(ValueError):destination(url)


def test_exact_owner_https_destination_and_independent_signing_key_are_preserved():
    value={'alice':{'url':'https://peer.fixture.invalid:9443/callback','secret':'private_signing_fixture_'+'b'*32}}
    peers={'alice':'private_peer_fixture_'+'a'*32}
    assert callbacks(value,peers)==value
    for changed in [peers['alice'],peers['alice']+'suffix','short']:
        with pytest.raises(ValueError):callbacks({'alice':{**value['alice'],'secret':changed}},peers)
    with pytest.raises(ValueError):callbacks({'unknown':value['alice']},peers)


def test_cross_peer_callback_key_cannot_be_reflected_in_other_peer_destination():
    peers={'alice':'private_peer_fixture_'+'a'*32,'bob':'private_peer_fixture_'+'b'*32}
    secret='private_signing_fixture_'+'c'*32
    with pytest.raises(ValueError):callbacks({'alice':{'url':'https://alice.fixture.invalid/'+secret,'secret':'private_signing_fixture_'+'d'*32},
        'bob':{'url':'https://bob.fixture.invalid/callback','secret':secret}},peers)
