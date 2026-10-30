"""Bounded in-memory AMR-NB encoding in the credential-free speech identity."""
import base64
import hashlib
from io import BytesIO

from .speech import decode,MAX_AUDIO_BYTES,MAX_SAMPLES,SpeechRefused

MAX_REPLY=4*((MAX_AUDIO_BYTES+2)//3)+4096


def duration_samples(raw):
    # The reviewed encoder fixes MR122, mono, 20-ms frames and disables DTX.
    # Count at the source receipt's 16-kHz timebase (encoded audio is 8 kHz).
    if (not isinstance(raw,bytes) or not raw.startswith(b'#!AMR\n') or not 6<len(raw)<=MAX_AUDIO_BYTES
            or (len(raw)-6)%32 or any(raw[index]!=0x3c for index in range(6,len(raw),32))):
        raise SpeechRefused('fixed 12.2-kbit AMR-NB frames required')
    return (len(raw)-6)//32*320


def encode(data):
    pcm,samples=decode(data)
    import av
    output=BytesIO()
    try:
        with av.open(output,'w',format='amr') as target:
            stream=target.add_stream('libopencore_amrnb',rate=8000);stream.layout='mono';stream.bit_rate=12200;stream.codec_context.options={'dtx':'0'}
            resampler=av.AudioResampler(format='s16',layout='mono',rate=8000)
            def append(frames):
                for frame in frames:
                    for packet in stream.encode(frame):target.mux(packet)
                    if output.tell()>MAX_AUDIO_BYTES:raise SpeechRefused('encoded voice exceeds byte limit')
            with av.open(BytesIO(pcm)) as source:
                for frame in source.decode(audio=0):append(resampler.resample(frame))
            append(resampler.resample(None))
            for packet in stream.encode(None):target.mux(packet)
        raw=output.getvalue()
        if not 1<=len(raw)<=MAX_AUDIO_BYTES or not raw.startswith(b'#!AMR\n'):
            raise SpeechRefused('native AMR-NB output required')
        _,count=decode(raw)
        if count!=duration_samples(raw):raise SpeechRefused('AMR frame duration differs from decoded samples')
        if abs(count-samples)>320:raise SpeechRefused('voice encoding changed source duration')
    except SpeechRefused:raise
    except Exception:raise SpeechRefused('local AMR-NB encoder unavailable or input refused') from None
    return {'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),
        'source_sha256':hashlib.sha256(data).hexdigest(),'samples':samples,'encoded_samples':count,'sample_rate':16000,'codec':'amr-nb-12200'}


def result(value,source):
    if (not isinstance(value,dict) or set(value)!={'data','sha256','source_sha256','samples','encoded_samples','sample_rate','codec'}
            or value['source_sha256']!=source or value['codec']!='amr-nb-12200' or type(value['samples']) is not int
            or not 1<=value['samples']<=MAX_SAMPLES or type(value['encoded_samples']) is not int
            or not 1<=value['encoded_samples']<=MAX_SAMPLES+320 or abs(value['encoded_samples']-value['samples'])>320 or type(value['sample_rate']) is not int or value['sample_rate']!=16000
            or not isinstance(value['data'],str) or not 1<=len(value['data'])<=4*((MAX_AUDIO_BYTES+2)//3)
            or not isinstance(value['sha256'],str)):
        raise SpeechRefused('exact source-bound local voice conversion receipt required')
    try:raw=base64.b64decode(value['data'],validate=True)
    except Exception:raise SpeechRefused('canonical encoded voice bytes required') from None
    if (not 1<=len(raw)<=MAX_AUDIO_BYTES or base64.b64encode(raw).decode()!=value['data']
            or hashlib.sha256(raw).hexdigest()!=value['sha256'] or duration_samples(raw)!=value['encoded_samples']):
        raise SpeechRefused('encoded voice checksum or container mismatch')
    return {'data':raw,'sha256':value['sha256'],'source_sha256':source,'samples':value['samples'],'encoded_samples':value['encoded_samples']}
