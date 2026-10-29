"""Private download URL/DNS and decoded consent contracts; no live media claim."""
import asyncio
from copy import deepcopy
import pytest

from haos.gateway_dingtalk_download import validate_url, public_address, PublicResolver
from haos.gateway_dingtalk_http import Failure
from haos.gateway_dingtalk_resource import classify


@pytest.mark.parametrize('url', ['http://cdn.example.org/file', 'https://127.0.0.1/file',
    'https://[::1]/file', 'https://localhost/file', 'https://user:private@cdn.example.org/file',
    'https://cdn.example.org:8443/file', 'https://cdn.example.org/file#fragment',
    'https://cdn.example.org./file', 'https://bad_label.example.org/file',
    'https://cdn.example.org\n/file', 'https://cdn.example.org%40other.example/file'])
def test_download_url_cannot_select_plaintext_credentials_numeric_private_host_or_unreviewed_port(url):
    with pytest.raises(Failure): validate_url(url)


def test_signed_download_url_retains_exact_escaped_path_and_query():
    url = 'https://cdn.example.org/a%2Fb?signature=opaque%2Bcapability%2Fvalue&part=1'
    assert validate_url(url) == url


@pytest.mark.parametrize('address', ['127.0.0.1', '0.0.0.0', '10.0.0.1', '172.16.0.1',
    '192.168.1.1', '169.254.169.254', '100.64.0.1', '224.0.0.1', '255.255.255.255',
    '::1', '::', 'fe80::1', 'fc00::1', 'ff02::1', 'fec0::1', '2001:db8::1',
    '::ffff:127.0.0.1', '::ffff:8.8.8.8', '64:ff9b::7f00:1', '2002:7f00:1::', 'not-an-address'])
def test_public_dns_filter_denies_local_metadata_cgnat_multicast_and_translation_tunnels(address):
    assert public_address(address) is False


@pytest.mark.parametrize('address', ['8.8.8.8', '1.1.1.1', '93.184.216.34',
                                    '2001:4860:4860::8888', '2606:4700:4700::1111'])
def test_public_dns_filter_accepts_ordinary_global_unicast(address):
    assert public_address(address) is True


def test_actual_loopback_dns_answer_cannot_become_a_download_socket_destination():
    async def check():
        resolver = PublicResolver()
        try:
            with pytest.raises(Failure): await resolver.resolve('localhost', 443)
        finally: await resolver.close()
    asyncio.run(check())


@pytest.mark.parametrize('kind,mime,data,flag', [
    ('document', 'application/octet-stream', b'#!AMR\nprivate-audio-fixture', 'allow_voice'),
    ('document', 'audio/ogg', b'OggSprivate-audio-fixture', 'allow_voice'),
    ('document', 'application/octet-stream', b'\0\0\0\x10ftypmp42\0\0\0\0', 'allow_video'),
])
def test_document_label_cannot_bypass_decoded_voice_or_video_permission(kind, mime, data, flag):
    spec = {'resource': {'kind': kind}, 'binding': {'capabilities': ['create'], 'allow_media': True}}
    with pytest.raises(PermissionError): classify(spec, mime, data)
    permitted = deepcopy(spec); permitted['binding'][flag] = True
    assert classify(permitted, mime, data)['kind'] == ('voice' if flag == 'allow_voice' else 'video')


def test_image_content_type_must_match_original_bytes():
    spec = {'resource': {'kind': 'image'}, 'binding': {'capabilities': ['create'], 'allow_media': True}}
    with pytest.raises(ValueError): classify(spec, 'image/jpeg', b'\x89PNG\r\n\x1a\nfixture')


def test_missing_service_account_fails_closed_before_private_resource_credentials_or_sdk(monkeypatch):
    from haos import gateway_runtime
    from haos.gateway_dingtalk_resource_process import resource
    def absent(_name): raise KeyError('fixture service account absent')
    monkeypatch.setattr(gateway_runtime.pwd,'getpwnam',absent)
    class CredentialsMustRemainUnread(dict):
        def __iter__(self): raise AssertionError('credentials examined before private identity gate')
    with pytest.raises(PermissionError,match='service identity is unavailable'):
        asyncio.run(resource(CredentialsMustRemainUnread(),'dingtalk',lambda:None,{}))
