"""Closed byte/duration receipts; actual native codec and ASR live in runtime probes."""
import base64
import hashlib
import pytest

from haos.audio_amr import result,duration_samples
from haos.speech import SpeechRefused
from haos.speech_service import request_bytes


def receipt():
    raw=b'#!AMR\n'+b'\x3c'+bytes(31)
    return {'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),
        'source_sha256':'a'*64,'samples':320,'encoded_samples':320,'sample_rate':16000,'codec':'amr-nb-12200'}


def test_amr_receipt_carries_source_and_complete_encoded_frame_duration_without_decoder_import():
    value=receipt();checked=result(value,'a'*64)
    assert checked['encoded_samples']==duration_samples(checked['data'])==320
    assert checked['samples']==320 and checked['source_sha256']=='a'*64


@pytest.mark.parametrize('change',[{'encoded_samples':True},{'encoded_samples':160},{'encoded_samples':-1},
    {'samples':True},{'samples':1.0},{'source_sha256':'b'*64},{'sha256':'0'*64},
    {'codec':'command'},{'sample_rate':8000},{'extra':'unreviewed'}])
def test_untrusted_duration_source_or_codec_receipts_are_refused(change):
    with pytest.raises(SpeechRefused):result({**receipt(),**change},'a'*64)


@pytest.mark.parametrize('data',[b'#!AMR\n',b'#!AMR\n'+b'\x3c'+bytes(30),
    b'#!AMR\n'+b'\x04'+bytes(31),b'OggS'+bytes(100)])
def test_other_formats_frame_modes_and_truncated_frames_cannot_supply_amr_duration(data):
    with pytest.raises(SpeechRefused):duration_samples(data)


@pytest.mark.parametrize('operation',['amr','opus'])
def test_speech_worker_admits_only_bounded_source_bytes_for_explicit_codec_operations(operation):
    data=b'fixture audio bytes';request={'data':base64.b64encode(data).decode(),
        'sha256':hashlib.sha256(data).hexdigest(),'operation':operation}
    assert request_bytes(request)==data
    for changed in [{**request,'operation':'ffmpeg -i /owner/private'},
        {**request,'operation':{}},{**request,'path':'/owner/private'},
        {**request,'sha256':'0'*64}]:
        with pytest.raises(SpeechRefused):request_bytes(changed)
