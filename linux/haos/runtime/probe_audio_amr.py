#!/usr/bin/env python3
"""Real pinned AMR-NB encoding/decoding and local Hermes ASR; no vendor account."""
import base64,hashlib,json,os,sys,tempfile,wave
from io import BytesIO
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.audio_amr import encode,result,duration_samples
    from haos.speech import decode,transcribe,SpeechRefused
    assets=Path(sys.argv[2]).resolve();source=(assets/'reference.flac').read_bytes();cases=[]
    source_hash=hashlib.sha256(source).hexdigest();encoded=encode(source);checked=result(encoded,source_hash)
    raw=checked['data'];_,count=decode(raw)
    assert encoded['samples']==176000 and count==encoded['encoded_samples']==duration_samples(raw)==176320
    assert encoded['codec']=='amr-nb-12200' and raw.startswith(b'#!AMR\n') and len(raw)==17638
    cases.append('actual_pinned_PyAV_libopencore_AMR_NB_12200_mono_8kHz_encoding_and_native_decode_with_source_bound_16kHz_duration_receipt')
    assert encode(source)==encoded
    cases.append('actual_encoder_repeated_reference_has_identical_frame_bytes_with_DTX_disabled')
    with tempfile.TemporaryDirectory(prefix='haos-amr-native-home-') as td:
        home=Path(td);config=home/'.hermes';config.mkdir()
        (config/'config.yaml').write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n')
        os.environ.update(HOME=str(home),HERMES_HOME=str(config),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        transcript=transcribe(raw,model_root=assets/'model',model_owner_uid=os.geteuid())
        assert 'ask not what your country can do for you' in transcript['transcript'].lower()
        assert 'ask what you can do for your country' in transcript['transcript'].lower()
        assert transcript['provider']=='local' and transcript['samples']==count
    cases.append('actual_pinned_Hermes_local_engine_recognizes_encoded_AMR_reference_without_account_or_lazy_install')
    for change in [{'codec':'ogg-opus'},{'encoded_samples':True},{'encoded_samples':176000},
        {'samples':True},{'sample_rate':8000},{'source_sha256':'0'*64},{'sha256':'0'*64},{'extra':'unreviewed'}]:
        try:result({**encoded,**change},source_hash)
        except SpeechRefused:pass
        else:raise AssertionError('changed source codec duration or output proof admitted')
    cases.append('source_hash_codec_duration_boolean_shape_and_checksum_tampering_refused')
    for damaged in [raw[:-1],raw[:6]+b'\x04'+raw[7:],raw+b'\0',b'#!AMR\n']:
        try:duration_samples(damaged)
        except SpeechRefused:pass
        else:raise AssertionError('wrong AMR framing accepted')
    cases.append('fixed_MR122_frame_TOC_and_complete_20ms_frame_lengths_required')
    output=BytesIO()
    with wave.open(output,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000);writer.writeframes(b'\0\0'*(121*16000))
    for data in [b'',b'not audio',b'#EXTM3U\nfile:///owner/private.wav\n',output.getvalue()]:
        try:encode(data)
        except SpeechRefused:pass
        else:raise AssertionError('unbounded malformed or external-reference source admitted')
    cases.append('actual_native_decoder_refuses_empty_malformed_external_playlist_and_overlong_source_before_encoding')
    report={'passed':len(cases),'cases':cases,'encoded':{key:value for key,value in encoded.items() if key!='data'},
        'scope':'Actual frozen PyAV encoder/decoder and actual pinned Hermes local ASR with verified public model/reference fixture.',
        'speech_socket_UID_gateway_delivery_live_account_playback_or_installed_acceptance':False}
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
