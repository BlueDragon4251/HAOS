from email.message import EmailMessage
from email import policy as mail_policy
import hashlib
import pytest

from haos.gateway_email import PreparedEmailPolicy,scope
from haos.gateway_email_media import manifest,permit
from haos.gateway_email_admission import Refused


PNG=b'\x89PNG\r\n\x1a\n'+b'bounded image bytes'
MP4=(24).to_bytes(4,'big')+b'ftypisom'+b'\0'*12


def message(items):
    msg=EmailMessage();msg['From']='owner@example.invalid';msg['Message-ID']='<source@example.invalid>'
    msg.set_content('Inspect the approved files.')
    for data,mime,name in items:
        major,minor=mime.split('/');msg.add_attachment(data,maintype=major,subtype=minor,filename=name)
    return msg.as_bytes(policy=mail_policy.SMTP)


def configuration(**flags):
    value={'address':'haos@example.invalid','imap_host':'imap.example.invalid','imap_port':993}
    binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1,**flags}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
    envelope={'platform':'email','sender':binding['sender'],'chat':binding['chat'],'scope':binding['scope'],'thread':'',
        'message_id':'a'*64,'is_bot':False,'text':'Inspect the approved files.'}
    return config,envelope


def test_mime_manifest_keeps_exact_bytes_and_separates_image_document_voice_and_video():
    sources=[(PNG,'image/png','../../owner-secret.png'),(b'A bounded PDF','application/pdf','document.pdf'),
        (b'RIFFvoice-fixture','audio/wav','voice.wav'),(MP4,'video/mp4','clip.mp4')]
    result=manifest(message(sources))
    assert [row['kind'] for row in result]==['image','document','voice','video']
    for index,(row,(data,mime,name)) in enumerate(zip(result,sources)):
        assert row['index']==index and row['mime']==mime and row['sha256']==hashlib.sha256(data).hexdigest()
        assert row['size']==len(data) and row['filename_sha256']==hashlib.sha256(name.encode()).hexdigest()
        assert row['native_filename']==f'attachment-{index}.'+('png' if index==0 else 'bin')
        assert 'owner-secret' not in str(row) and '/' not in row['native_filename']


def test_other_images_remain_documents_under_the_existing_png_jpeg_model_contract():
    result=manifest(message([(b'GIF89a fixture','image/gif','image.gif')]))
    assert result[0]['kind']=='document' and result[0]['native_filename']=='attachment-0.bin'


@pytest.mark.parametrize('items',[
    [(b'data','application/pdf',str(index)+'.pdf') for index in range(5)],
    [(b'x'*(8*1024*1024+1),'application/pdf','large.pdf')],
    [(PNG+b'x'*(1100*1024),'image/png',str(index)+'.png') for index in range(2)],
    [(b'not an image','image/png','fake.png')],[(MP4,'video/webm','unsupported.webm')],
    [(b'not ISO media','video/mp4','fake.mp4')],[(b'','application/pdf','empty.pdf')],
])
def test_unsupported_or_oversized_mime_is_refused_before_native_cache_writes(items):
    with pytest.raises(Refused) as caught:manifest(message(items))
    assert caught.value.reason=='unsupported-content'


def test_excessive_mime_depth_and_duplicate_part_type_are_refused():
    leaf=EmailMessage();leaf.set_content('A bounded body')
    for _index in range(18):
        parent=EmailMessage();parent.make_mixed();parent.attach(leaf);leaf=parent
    with pytest.raises(Refused):manifest(leaf.as_bytes(policy=mail_policy.SMTP))
    raw=message([(b'data','application/pdf','file.pdf')]).replace(b'Content-Type: application/pdf',
        b'Content-Type: application/pdf\r\nContent-Type: audio/wav')
    with pytest.raises(Refused):manifest(raw)


@pytest.mark.parametrize('kind,flags,expected',[
    ('image',{'allow_media':True},True),('document',{'allow_media':True},True),
    ('voice',{'allow_media':True},False),('voice',{'allow_voice':True},True),
    ('video',{'allow_media':True},False),('video',{'allow_video':True},True),('document',{},False),
])
def test_each_attachment_kind_needs_its_own_explicit_current_owner_approval(kind,flags,expected):
    config,envelope=configuration(**flags);policy=PreparedEmailPolicy(config)
    if expected:assert permit(policy,'email',envelope,[{'kind':kind}])['id']=='owner'
    else:
        with pytest.raises(Refused) as caught:permit(policy,'email',envelope,[{'kind':kind}])
        assert caught.value.reason=='media-not-approved'


def test_media_cannot_change_an_exact_control_command_into_an_agent_mission():
    config,envelope=configuration(allow_media=True);envelope['text']='/status 123'
    with pytest.raises(Refused) as caught:permit(PreparedEmailPolicy(config),'email',envelope,[{'kind':'document'}])
    assert caught.value.reason=='unsupported-content'


@pytest.mark.parametrize('flag',['allow_media','allow_voice','allow_video','allow_outbound_media'])
def test_prepared_email_approval_flags_are_boolean_and_require_the_corresponding_right(flag):
    config,_envelope=configuration(**{flag:'true'})
    with pytest.raises(ValueError):PreparedEmailPolicy(config)
    config,_envelope=configuration(**{flag:True})
    config['bindings'][0]['capabilities']=['create'] if flag=='allow_outbound_media' else ['read']
    with pytest.raises(ValueError):PreparedEmailPolicy(config)
