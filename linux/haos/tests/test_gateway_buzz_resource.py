"""No private media authority from a sender URL, declared file label or MIME."""
import pytest

from haos.gateway_buzz import resource_origin,credentials
from haos.gateway_buzz_resource import classify
from haos.gateway_buzz_admission import Refused

ACCOUNT={'private_key':'1'*64,'public_key':'2'*64,'relay_url':'https://buzz.fixture.invalid',
    'channels':['01234567-89ab-4cde-8012-3456789abcde']}


@pytest.mark.parametrize('url',['https://buzz.fixture.invalid/admin/export','https://buzz.fixture.invalid/media/../admin',
    'https://buzz.fixture.invalid/media/'+('a'*64)+'/extra','https://foreign.fixture.invalid/media/'+('a'*64),
    'http://buzz.fixture.invalid/media/'+('a'*64),'https://user:password@buzz.fixture.invalid/media/'+('a'*64),
    'https://buzz.fixture.invalid/media/'+('a'*64)+'#fragment'])
def test_signed_source_cannot_spend_private_relay_identity_outside_exact_native_media_paths_or_owner_origins(url):
    with pytest.raises((ValueError,PermissionError)):resource_origin(ACCOUNT,url)


def test_owner_approved_foreign_origin_is_public_mode_and_never_private_relay_authentication():
    value=credentials({**ACCOUNT,'attachment_origins':['https://public.fixture.invalid']})
    assert resource_origin(value,'https://public.fixture.invalid/images/asset.png?version=1')=='public'
    assert resource_origin(value,'https://buzz.fixture.invalid/media/'+('a'*64)+'.thumb.jpg')=='relay'
    with pytest.raises(ValueError):credentials({**ACCOUNT,'attachment_origins':['https://public.fixture.invalid']*2})


@pytest.mark.parametrize('data',[b'ID3voice',b'fLaCvoice',b'OggSvoice',b'RIFF'+bytes(4)+b'WAVEvoice',
    b'\0\0\0\x18ftypisom'+bytes(12)])
def test_octet_stream_or_document_label_cannot_downgrade_audio_or_video_to_general_media(data):
    spec={'resource':{'kind':'document','mime_type':'application/octet-stream'},'binding':{'allow_media':True}}
    with pytest.raises(Refused) as result:classify(spec,data)
    assert result.value.reason=='independent-decoded-media-consent-required'


def test_voice_permission_and_actual_wav_magic_produce_voice_not_document_with_accurate_mime():
    data=b'RIFF'+bytes(4)+b'WAVEvoice'
    meta,mime=classify({'resource':{'kind':'document'},'binding':{'allow_voice':True}},data)
    assert meta['kind']=='voice' and mime=='audio/wav'
