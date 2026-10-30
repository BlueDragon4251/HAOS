#!/usr/bin/env python3
"""Actual in-memory MP4 decoding/PNG preview and closed source-bound metadata."""
import hashlib,json,sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.media_thumbnail import thumbnail,result
    from haos.speech import SpeechRefused
    from video_fixture import movie
    data=movie();source=hashlib.sha256(data).hexdigest();encoded=thumbnail(data);checked=result(encoded,source);cases=[]
    assert checked['width']==320 and checked['height']==180 and checked['duration_ms']==1000
    assert checked['thumbnail_width']==320 and checked['thumbnail_height']==180
    assert checked['data'].startswith(b'\x89PNG\r\n\x1a\n') and len(json.dumps(encoded))>96*1024
    import av
    from io import BytesIO
    with av.open(BytesIO(checked['data'])) as image:
        frame=next(image.decode(video=0));assert frame.width==320 and frame.height==180
    cases.append('actual_frozen_MPEG4_MP4_decoder_PNG_encoder_and_decode_produce_source_bound_preview_larger_than_text_RPC_limit')
    assert thumbnail(data)==encoded
    cases.append('actual_repeated_video_preview_has_identical_native_PNG_bytes')
    scaled=thumbnail(movie(width=640,height=360));assert scaled['thumbnail_width']==320 and scaled['thumbnail_height']==180
    cases.append('actual_native_preview_preserves_aspect_ratio_and_caps_decoded_cover_dimensions')
    for name,bad in [('unknown',b'not video'),('playlist',b'#EXTM3U\nfile:///owner/private.mp4\n'),
        ('multi-video',movie(streams=2)),('overlong',movie(width=64,height=32,frames=121)),('wide',movie(width=4608,height=16))]:
        try:thumbnail(bad)
        except SpeechRefused:pass
        else:raise AssertionError(name+' source admitted')
        cases.append('actual_decoder_'+name+'_refused_without_external_program_or_protocol')
    for changed in [{'width':True},{'width':321},{'thumbnail_width':0},{'thumbnail_height':181},{'duration_ms':True},
        {'source_sha256':'0'*64},{'sha256':'0'*64},{'codec':'arbitrary-codec'},{'extra':'unreviewed'}]:
        try:result({**encoded,**changed},source)
        except SpeechRefused:pass
        else:raise AssertionError('changed preview source dimensions duration codec or shape admitted')
    cases.append('source_codec_checksum_duration_boolean_and_PNG_dimension_tampering_refused')
    report={'passed':len(cases),'cases':cases,'native':{key:value for key,value in encoded.items() if key!='data'},
        'scope':'Actual frozen PyAV MP4 decoder and PNG encoder on deterministic synthetic video; not a vendor account or device playback test.',
        'kernel_UID_RPC_controller_artifact_vendor_delivery_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
