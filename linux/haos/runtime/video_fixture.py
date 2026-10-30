"""Deterministic public synthetic MP4 fixture, produced by the actual frozen codec."""
from io import BytesIO


def movie(*,width=320,height=180,frames=1,streams=1):
    import av,numpy
    pixels=numpy.random.default_rng(17).integers(0,256,(height,width,3),dtype=numpy.uint8)
    output=BytesIO()
    with av.open(output,'w',format='mp4') as target:
        tracks=[]
        for _ in range(streams):
            stream=target.add_stream('mpeg4',rate=1);stream.width=width;stream.height=height
            stream.pix_fmt='yuv420p';stream.bit_rate=8000000;stream.codec_context.thread_count=1;tracks.append(stream)
        for index in range(frames):
            for stream in tracks:
                frame=av.VideoFrame.from_ndarray(pixels,format='rgb24');frame.pts=index
                for packet in stream.encode(frame):target.mux(packet)
        for stream in tracks:
            for packet in stream.encode(None):target.mux(packet)
    return output.getvalue()
