"""Bounded in-memory MP4 preview in the credential-free local media/speech worker."""
import base64
from fractions import Fraction
import hashlib
from io import BytesIO
import struct

from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES,describe
from .speech import SpeechRefused

MAX_REPLY=4*((MAX_IMAGE_BYTES+2)//3)+4096


def thumbnail(data):
    try:
        if describe(data,'video')['format']!='mp4':raise SpeechRefused('native Robot output requires MP4 video')
        import av
        output=BytesIO()
        with av.open(BytesIO(data),options={'protocol_whitelist':'pipe','format_whitelist':'mov'}) as source:
            if len(source.streams.video)!=1 or len(source.streams.audio)>1 or len(source.streams)>2:
                raise SpeechRefused('one bounded MP4 video stream required')
            stream=source.streams.video[0];stream.codec_context.thread_count=1
            if not 1<=stream.width<=4096 or not 1<=stream.height<=4096:
                raise SpeechRefused('bounded source video dimensions required')
            duration=(Fraction(source.duration,av.time_base)*1000 if source.duration is not None else
                Fraction(stream.duration)*stream.time_base*1000 if stream.duration is not None and stream.time_base is not None else None)
            if duration is None or not 0<duration<=120000:raise SpeechRefused('video duration must be known and at most two minutes')
            duration_ms=(duration.numerator+duration.denominator-1)//duration.denominator
            frame=next(source.decode(video=0))
            width,height=frame.width,frame.height
            if not 1<=width<=4096 or not 1<=height<=4096:raise SpeechRefused('decoded video dimensions exceed limit')
            ratio=min(Fraction(1),Fraction(320,width),Fraction(320,height))
            preview_width=max(1,int(width*ratio));preview_height=max(1,int(height*ratio))
            preview=frame.reformat(width=preview_width,height=preview_height,format='rgb24')
            preview.pts=0;preview.time_base=Fraction(1,1)
            with av.open(output,'w',format='image2pipe') as target:
                image=target.add_stream('png',rate=1);image.width=preview_width;image.height=preview_height
                image.pix_fmt='rgb24';image.codec_context.thread_count=1
                for packet in image.encode(preview):target.mux(packet)
                for packet in image.encode(None):target.mux(packet)
        raw=output.getvalue()
        if not 1<=len(raw)<=MAX_IMAGE_BYTES or describe(raw,'image')['format']!='png':
            raise SpeechRefused('bounded native PNG thumbnail required')
    except SpeechRefused:raise
    except Exception:raise SpeechRefused('local MP4 thumbnail decoder unavailable or input refused') from None
    return {'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),
        'source_sha256':hashlib.sha256(data).hexdigest(),'width':width,'height':height,
        'thumbnail_width':preview_width,'thumbnail_height':preview_height,'duration_ms':duration_ms,'codec':'png-thumbnail-v1'}


def result(value,source):
    if (not isinstance(value,dict) or set(value)!={'data','sha256','source_sha256','width','height','thumbnail_width','thumbnail_height','duration_ms','codec'}
            or value['source_sha256']!=source or value['codec']!='png-thumbnail-v1'
            or any(type(value[key]) is not int or not 1<=value[key]<=4096 for key in ['width','height'])
            or any(type(value[key]) is not int or not 1<=value[key]<=320 for key in ['thumbnail_width','thumbnail_height'])
            or type(value['duration_ms']) is not int or not 1<=value['duration_ms']<=120000
            or not isinstance(value['data'],str) or not 1<=len(value['data'])<=4*((MAX_IMAGE_BYTES+2)//3)
            or not isinstance(value['sha256'],str)):
        raise SpeechRefused('exact source-bound bounded video preview receipt required')
    ratio=min(Fraction(1),Fraction(320,value['width']),Fraction(320,value['height']))
    if (value['thumbnail_width']!=max(1,int(value['width']*ratio))
            or value['thumbnail_height']!=max(1,int(value['height']*ratio))):
        raise SpeechRefused('thumbnail aspect ratio differs from bounded source dimensions')
    try:raw=base64.b64decode(value['data'],validate=True)
    except Exception:raise SpeechRefused('canonical PNG thumbnail encoding required') from None
    if (not 24<=len(raw)<=MAX_IMAGE_BYTES or base64.b64encode(raw).decode()!=value['data']
            or hashlib.sha256(raw).hexdigest()!=value['sha256'] or raw[:8]!=b'\x89PNG\r\n\x1a\n'
            or raw[12:16]!=b'IHDR' or struct.unpack('>II',raw[16:24])!=(value['thumbnail_width'],value['thumbnail_height'])):
        raise SpeechRefused('thumbnail bytes, dimensions or checksum changed')
    return {**{key:part for key,part in value.items() if key not in {'data','codec'}},'data':raw}
