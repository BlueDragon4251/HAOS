"""Independent media consent and exact URI authority without optional SDK imports."""
import pytest
from haos.gateway_a2a import PreparedA2APolicy
from haos.gateway_a2a_media import origins,target,classify
from test_gateway_a2a import binding


@pytest.mark.parametrize('flag',['allow_media','allow_voice','allow_video','allow_outbound_media'])
@pytest.mark.parametrize('value',[1,'true',None])
def test_media_flags_cannot_coerce_numbers_strings_or_null_into_permissions(flag,value):
    b={**binding(),flag:value}
    with pytest.raises(ValueError):PreparedA2APolicy({'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]})


@pytest.mark.parametrize('flag,caps',[('allow_media',['read']),('allow_voice',['read']),('allow_video',['read']),('allow_outbound_media',['create'])])
def test_kind_permission_cannot_create_missing_mission_or_read_capability(flag,caps):
    b={**binding(),'capabilities':caps,flag:True}
    with pytest.raises(ValueError):PreparedA2APolicy({'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]})


@pytest.mark.parametrize('selected',[{'unknown':['https://files.example.invalid']},{'alice':[]},
    {'alice':['http://files.example.invalid']},{'alice':['https://user:secret@files.example.invalid']},
    {'alice':['https://files.example.invalid/path']},{'alice':['https://files.example.invalid?token=secret']},
    {'alice':['https://files.example.invalid','https://files.example.invalid:443/']}])
def test_download_permission_is_exact_peer_and_origin_without_credentials_paths_or_duplicate_aliases(selected):
    with pytest.raises(ValueError):origins(selected,{'alice':'private-fixture'})


@pytest.mark.parametrize('url',['http://files.example.invalid/file','https://files.example.invalid.evil/file',
    'https://files.example.invalid:4443/file','https://files.example.invalid@127.0.0.1/file',
    'https://files.example.invalid/file#other','https://files.example.invalid/file\r\nX-Header: injected'])
def test_uri_cannot_escape_approved_origin_scheme_port_authority_or_header_frame(url):
    value={'download_origins':{'alice':['https://files.example.invalid']}}
    with pytest.raises((ValueError,PermissionError)):target(value,'alice',url)


def test_exact_origin_permission_allows_signed_query_without_granting_another_peer():
    selected=origins({'alice':['https://FILES.example.invalid:443/']},{'alice':'private-fixture','bob':'other-private-fixture'})
    assert selected=={'alice':['https://files.example.invalid']}
    value={'download_origins':selected};url='https://files.example.invalid/object?signature=private-fixture-source'
    assert target(value,'alice',url)==url
    with pytest.raises(PermissionError):target(value,'bob',url)


@pytest.mark.parametrize('raw',[b'fLaCprivate speech',b'OggSprivate voice',b'RIFF1234WAVEprivate',b'ID3private',b'\x89PNG\r\n\x1a\nimage'])
def test_known_audio_or_image_bytes_cannot_be_downgraded_into_generic_document_consent(raw):
    with pytest.raises(ValueError):classify('document','application/octet-stream',raw)
