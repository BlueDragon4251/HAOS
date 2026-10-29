#!/usr/bin/env python3
"""Actual bounded PyAV voice encoding, no account/model/path/command provider."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import wave


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.audio_opus import encode,result
    from haos.speech import decode,SpeechRefused
    audio=(Path(sys.argv[2])/'reference.flac').read_bytes();cases=[]
    pcm,samples=decode(audio)
    sources=[('flac',audio),('wav',pcm)]
    import av
    for label,container,codec in [('mp3','mp3','libmp3lame'),('m4a','mp4','aac')]:
        buffer=BytesIO()
        with av.open(buffer,'w',format=container) as target:
            stream=target.add_stream(codec,rate=16000);stream.layout='mono'
            with av.open(BytesIO(pcm)) as source:
                for frame in source.decode(audio=0):
                    for packet in stream.encode(frame):target.mux(packet)
                for packet in stream.encode(None):target.mux(packet)
        sources.append((label,buffer.getvalue()))
    for label,data in sources:
        _,count=decode(data);receipt=encode(data);checked=result(receipt,hashlib.sha256(data).hexdigest())
        assert checked['samples']==count and decode(checked['data'])[1]==count
        assert receipt['codec']=='ogg-opus' and len(checked['data'])<1024*1024
        cases.append('actual_'+label+'_decoded_and_encoded_to_duration_preserving_mono_Opus')
    oversized=BytesIO()
    with wave.open(oversized,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(b'\0\0'*(121*16000))
    for label,data in [('invalid',b'not audio'),('playlist',b'#EXTM3U\nhttps://other.invalid/source\n'),('too_long',oversized.getvalue())]:
        try:encode(data)
        except SpeechRefused:pass
        else:raise AssertionError('unreviewed conversion source accepted')
        cases.append('actual_'+label+'_source_refused_without_model_or_remote_fallback')
    report={'passed':len(cases),'cases':cases,'actual_codec':True,'private_service_identity_and_transport':False}
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
