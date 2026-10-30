import pytest
from haos.gateway_mattermost import server_url, validate_credentials


@pytest.mark.parametrize('url', [
    'http://chat.example', 'https://user:pass@chat.example', 'https://chat.example?token=x',
    'https://chat.example#x', 'https://chat.example?', 'https://chat.example#',
    'https://chat.example/a/../b', 'https://chat.example/%2e%2e',
    'https://chat.example//a', 'https://chat.example\\@evil.example',
    'https://chat.example:0', 'https://chat.example:65536', 'https://bad..example',
    'https://-bad.example', 'https://chat.example/white space', ' https://chat.example',
])
def test_owner_server_rejects_ambiguous_or_unprotected_routes(url):
    with pytest.raises(ValueError): server_url(url)


@pytest.mark.parametrize('url,expected', [
    ('https://Chat.Example:443/prefix/', 'https://chat.example/prefix'),
    ('https://192.168.1.7:8443', 'https://192.168.1.7:8443'),
    ('https://[fd00::7]/prefix', 'https://[fd00::7]/prefix'),
])
def test_explicit_private_owner_server_is_supported(url, expected):
    assert validate_credentials('x' * 26, url) == expected
