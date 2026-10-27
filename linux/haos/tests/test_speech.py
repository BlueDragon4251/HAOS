import hashlib
import os

import pytest

from haos import speech


@pytest.mark.parametrize('value',[None,'not bytes',b'',b'x'*(speech.MAX_AUDIO_BYTES+1)])
def test_unbounded_speech_input_refused_before_optional_decoder_or_model(value):
    with pytest.raises(speech.SpeechRefused):speech.decode(value)
    with pytest.raises(speech.SpeechRefused):speech.transcribe(value)


@pytest.mark.parametrize('change',['valid','checksum','mode','directory','symlink','hardlink','size'])
def test_model_open_requires_reviewed_bytes_and_readonly_regular_single_link(monkeypatch,tmp_path,change):
    model=tmp_path/'model';model.mkdir(mode=0o755)
    payload=b'reviewed local model fixture';path=model/'model.bin';path.write_bytes(payload);path.chmod(0o644)
    monkeypatch.setattr(speech,'FILES',{'model.bin':(len(payload),hashlib.sha256(payload).hexdigest())})
    if change=='checksum':path.write_bytes(b'x'*len(payload))
    if change=='mode':path.chmod(0o666)
    if change=='directory':model.chmod(0o777)
    if change=='symlink':path.rename(model/'original');path.symlink_to(model/'original')
    if change=='hardlink':os.link(path,model/'other')
    if change=='size':path.write_bytes(payload+b'x')
    if change=='valid':assert speech.verify_model(model,owner_uid=os.geteuid())==model
    else:
        with pytest.raises((speech.SpeechRefused,PermissionError,OSError)):speech.verify_model(model,owner_uid=os.geteuid())


@pytest.mark.parametrize('change',['checksum','noncanonical','extra','empty','oversize','path'])
def test_private_voice_request_has_no_caller_paths_commands_or_unbounded_data(change):
    import base64
    from haos.speech_service import request_bytes
    value={'data':base64.b64encode(b'audio').decode(),'sha256':hashlib.sha256(b'audio').hexdigest()}
    if change=='checksum':value['sha256']='a'*64
    if change=='noncanonical':value['data']='YXVkaW8=\n'
    if change=='extra':value['command']='run arbitrary code'
    if change=='empty':value['data']=''
    if change=='oversize':value['data']='a'*(speech.MAX_AUDIO_BYTES*4//3+5)
    if change=='path':value={'path':'/owner/private'}
    with pytest.raises(speech.SpeechRefused):request_bytes(value)
