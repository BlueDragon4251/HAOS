#!/usr/bin/env python3
"""Actual pinned local STT, format bounds and reviewed offline fixture data."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import wave


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.speech import decode,transcribe,SpeechRefused
    assets=Path(sys.argv[2]).resolve();cases=[]
    def wav(samples,channels=1):
        output=BytesIO()
        with wave.open(output,'wb') as writer:
            writer.setnchannels(channels);writer.setsampwidth(2);writer.setframerate(16000)
            writer.writeframes(b'\0\0'*samples*channels)
        return output.getvalue()
    for name,data in [('empty',b''),('unknown',b'not audio'),('too_long',wav(121*16000)),
            ('three_channels',wav(1000,3)),('playlist',b'#EXTM3U\n#EXT-X-TARGETDURATION:1\nfile:///owner/private.wav\n')]:
        try:decode(data)
        except SpeechRefused:pass
        else:raise AssertionError(name+' voice source admitted')
        cases.append('actual_decoder_'+name+'_refused')
    pcm,samples=decode((assets/'reference.flac').read_bytes());assert samples==176000
    cases.append('actual_flac_decode_preserves_reference_duration_as_bounded_mono_pcm')
    import av
    output=BytesIO()
    with av.open(output,'w',format='mp4') as encoded:
        stream=encoded.add_stream('aac',rate=16000);stream.layout='mono'
        with av.open(BytesIO(pcm)) as source:
            for frame in source.decode(audio=0):
                for packet in stream.encode(frame):encoded.mux(packet)
            for packet in stream.encode(None):encoded.mux(packet)
    decoded,count=decode(output.getvalue());assert 176000<=count<180000 and len(decoded)<=360044
    cases.append('actual_aac_m4a_container_roundtrip_is_accepted_without_external_protocols')
    from caf_fixture import encode
    caf_bytes=encode(pcm)
    decoded,caf_samples=decode(caf_bytes)
    assert caf_samples==176000 and decoded==pcm
    cases.append('actual_CAF_decoder_preserves_exact_approved_PCM_without_external_protocols')
    try:decode(encode(wav(121*16000)))
    except SpeechRefused as error:assert 'two-minute' in str(error)
    else:raise AssertionError('CAF bypassed the existing voice duration limit')
    cases.append('actual_CAF_cannot_bypass_existing_two_minute_voice_limit')
    with tempfile.TemporaryDirectory(prefix='haos-stt-native-home-') as temporary:
        home=Path(temporary);config=home/'.hermes';config.mkdir()
        (config/'config.yaml').write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n')
        os.environ.update(HOME=str(home),HERMES_HOME=str(config),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        result=transcribe((assets/'reference.flac').read_bytes(),model_root=assets/'model',model_owner_uid=os.geteuid())
        assert 'ask not what your country can do for you' in result['transcript'].lower()
        assert 'ask what you can do for your country' in result['transcript'].lower()
        assert result['provider']=='local' and result['samples']==176000
        caf_result=transcribe(caf_bytes,model_root=assets/'model',model_owner_uid=os.geteuid())
        assert 'ask not what your country can do for you' in caf_result['transcript'].lower()
        assert 'ask what you can do for your country' in caf_result['transcript'].lower()
        assert caf_result['provider']=='local' and caf_result['samples']==176000
    cases.append('actual_pinned_hermes_local_engine_recognizes_reference_without_account_or_lazy_install')
    cases.append('actual_pinned_hermes_local_engine_recognizes_Photon_CAF_voice_without_cloud_or_path_input')
    report={'passed':len(cases),'cases':cases,'native':{key:value for key,value in result.items() if key!='transcript'},
        'external_account_line_voice_or_installed_acceptance':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
