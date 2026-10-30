"""Source-specific input-media contracts and real private SQLite retention."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest

from haos.gateway import Conflict,digest
from haos.gateway_google_chat_admission import approve,Refused
from haos.gateway_google_chat_resources import specifications,classify,retained
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,policy,event


def media(*,mime='image/png',allow=True,text='Describe the attached item'):
    selected=policy(allow_media=allow,allow_voice=allow,allow_video=allow)
    data=event();data['message']['text']=data['message']['argumentText']=text
    resource=data['message']['name']+'/attachments/resource1'
    data['message']['attachment']=[{'name':resource,'contentType':mime,'attachmentDataRef':{'resourceName':resource},
        'downloadUri':'https://unapproved.invalid/private-download-is-never-used'}]
    raw=json.dumps(data).encode();proof=approve(selected,'google',account(),raw);envelope={**proof['envelope'],'text':text}
    return selected,data,raw,proof,envelope


def test_resource_capability_pins_original_message_account_sender_thread_kind_and_ignores_arbitrary_download_URL():
    selected,data,raw,proof,envelope=media();specs=specifications(selected,'google',account(),raw,proof,envelope)
    assert specs==[{'index':0,'resource':envelope['message_id']+'/attachments/resource1','mime':'image/png','kind':'image'}]
    assert all('unapproved.invalid' not in str(item) for item in specs)
    with pytest.raises(ValueError):__import__('haos.gateway',fromlist=['GatewayPolicy']).GatewayPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[]})


@pytest.mark.parametrize('case',['foreign-message','foreign-name','missing-ref','opaque-ref','extra-ref','bad-mime','unsupported-image','unsupported-video','command','changed-original','changed-envelope','withdrawn'])
def test_unapproved_or_ambiguous_media_never_produces_a_read_capability(case):
    selected,data,raw,proof,envelope=media();attachment=data['message']['attachment'][0]
    if case=='foreign-message':attachment['attachmentDataRef']['resourceName']='spaces/space1/messages/another/attachments/resource1'
    elif case=='foreign-name':attachment['name']='spaces/another/messages/msg/attachments/resource1'
    elif case=='missing-ref':attachment.pop('attachmentDataRef')
    elif case=='opaque-ref':attachment['attachmentDataRef']['resourceName']='unscoped-download-alias'
    elif case=='extra-ref':attachment['attachmentDataRef']['foreign']='other'
    elif case=='bad-mime':attachment['contentType']='image/png\r\nForeign: value'
    elif case=='unsupported-image':attachment['contentType']='image/svg+xml'
    elif case=='unsupported-video':attachment['contentType']='video/unknown'
    elif case=='command':envelope['text']='/status'
    elif case=='changed-original':raw+=b' '
    elif case=='changed-envelope':envelope['thread']='spaces/space1/threads/other'
    elif case=='withdrawn':selected.bindings.clear()
    if case not in {'command','changed-original','changed-envelope','withdrawn'}:
        raw=json.dumps(data).encode();proof=approve(selected,'google',account(),raw)
    with pytest.raises((PermissionError,ValueError)):specifications(selected,'google',account(),raw,proof,envelope)


@pytest.mark.parametrize('mime,kind,data',[
    ('image/png','image',b'\x89PNG\r\n\x1a\nprivate local bytes'),('image/jpeg','image',b'\xff\xd8\xffprivate local bytes'),
    ('audio/ogg','voice',b'OggSprivate local bytes'),('video/mp4','video',b'\x00\x00\x00\x18ftypisom'+b'0'*20),
    ('application/pdf','document',b'%PDF local fixture')])
def test_declared_media_kinds_have_exact_byte_descriptors_and_cannot_be_relabelled(mime,kind,data):
    selected,event,raw,proof,envelope=media(mime=mime);spec=specifications(selected,'google',account(),raw,proof,envelope)[0]
    assert spec['kind']==kind and classify(spec,data)['kind']==kind
    if kind=='image':
        with pytest.raises((ValueError,PermissionError)):classify(spec,b'not an image')
        with pytest.raises((ValueError,PermissionError)):classify({**spec,'mime':'image/jpeg' if mime=='image/png' else 'image/png'},data)


def test_retained_media_is_committed_once_replayed_without_read_and_purged_or_damaged_bytes_are_never_restored(tmp_path):
    tmp_path.chmod(0o700);selected,event,raw,proof,envelope=media();inbox=NativeInbox(tmp_path/'media.sqlite',Redactor([]));calls=[]
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox,connector='google',policy=lambda:selected),_haos_google_value=account(),_haos_google_check=lambda:None)
    specs=specifications(selected,'google',account(),raw,proof,envelope);data=b'\x89PNG\r\n\x1a\nactual private bytes'
    async def read(*_args):calls.append('read');return data
    def run():return asyncio.run(retained(adapter,'a'*64,raw,proof,envelope,specs,reader=read))
    first=run();assert len(calls)==1 and first[0]['item']['data']==data
    assert run()==first and len(calls)==1
    identity=first[0]['item']['id'];inbox.db.execute("UPDATE native_media_cache SET state='purged',data=NULL WHERE id=?",(identity,))
    with pytest.raises((Conflict,PermissionError)):run()
    assert len(calls)==1
    inbox.db.execute("UPDATE native_media_cache SET state='cached',data=? WHERE id=?",(data+b'changed',identity))
    with pytest.raises((Conflict,PermissionError)):run()
    assert len(calls)==1;inbox.close()


def test_first_media_identity_precedes_blob_failure_and_changed_recovery_bytes_cannot_repair_it(tmp_path):
    import sqlite3
    tmp_path.chmod(0o700);selected,event,raw,proof,envelope=media();inbox=NativeInbox(tmp_path/'media.sqlite',Redactor([]));calls=[]
    from haos.gateway_media_relay import MediaCache
    MediaCache(inbox)
    inbox.db.execute("CREATE TRIGGER fail_blob BEFORE INSERT ON native_media_cache BEGIN SELECT RAISE(ABORT,'fixture disk full'); END")
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox,connector='google',policy=lambda:selected),_haos_google_value=account(),_haos_google_check=lambda:None)
    specs=specifications(selected,'google',account(),raw,proof,envelope);payload={'data':b'\x89PNG\r\n\x1a\nfirst bytes'}
    async def read(*_args):calls.append('read');return payload['data']
    def run():return asyncio.run(retained(adapter,'a'*64,raw,proof,envelope,specs,reader=read))
    with pytest.raises(sqlite3.IntegrityError):run()
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_input_media').fetchone()[0]==1
    assert inbox.db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]==0
    inbox.db.execute('DROP TRIGGER fail_blob');payload['data']+=b'changed'
    with pytest.raises(Conflict):run()
    assert inbox.db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]==0;inbox.close()


@pytest.mark.parametrize('upload',['opaque-private-upload-reference-fixture',None,[], 'bad\nvalue'])
def test_optional_native_upload_reference_cannot_supply_download_authority_or_become_a_public_specification(upload):
    selected,data,raw,proof,envelope=media()
    data['message']['attachment'][0]['attachmentDataRef']['attachmentUploadToken']=upload
    raw=json.dumps(data).encode();proof=approve(selected,'google',account(),raw)
    if isinstance(upload,str) and '\n' not in upload or upload is None:
        specs=specifications(selected,'google',account(),raw,proof,envelope)
        assert 'attachmentUploadToken' not in json.dumps(specs) and 'opaque-private' not in json.dumps(specs)
    else:
        with pytest.raises(Refused):specifications(selected,'google',account(),raw,proof,envelope)
