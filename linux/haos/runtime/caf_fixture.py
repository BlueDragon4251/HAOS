"""Public-audio CAF fixture encoded by the actual pinned PyAV/FFmpeg library."""
from io import BytesIO


def encode(pcm_wav):
    import av
    output = BytesIO()
    with av.open(output, 'w', format='caf') as encoded:
        stream = encoded.add_stream('pcm_s16le', rate=16000); stream.layout = 'mono'
        with av.open(BytesIO(pcm_wav)) as source:
            for frame in source.decode(audio=0):
                for packet in stream.encode(frame): encoded.mux(packet)
            for packet in stream.encode(None): encoded.mux(packet)
    data = output.getvalue()
    if not data.startswith(b'caff'): raise AssertionError('actual CAF container required')
    return data
