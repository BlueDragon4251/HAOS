"""Closed, bounded conversion wire contracts; actual codec uses runtime probes."""
import base64
import hashlib
import pytest
from haos.audio_opus import result
from haos.speech import SpeechRefused
from haos.speech_service import request_bytes


def test_only_fixed_opus_operation_extends_existing_path_free_audio_request():
    raw=b'audio';request={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),'operation':'opus'}
    assert request_bytes(request)==raw
    for changed in [{'operation':'command'},{'operation':'cloud'},{'path':'/owner/private'},{'command':'ffmpeg'}]:
        with pytest.raises(SpeechRefused):request_bytes({**request,**changed})


@pytest.mark.parametrize('change',[{'source_sha256':'b'*64},{'samples':True},{'sample_rate':True},
    {'codec':'external'},{'data':'!!!!'},{'sha256':'b'*64},{'path':'/owner/private'}])
def test_encoded_receipt_rejects_changed_source_shape_or_extra_paths(change):
    raw=b'OggS'+b'OpusHead'+b'fixture'
    value={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),
        'source_sha256':'a'*64,'samples':16000,'sample_rate':16000,'codec':'ogg-opus'}
    with pytest.raises(SpeechRefused):result({**value,**change},'a'*64)
