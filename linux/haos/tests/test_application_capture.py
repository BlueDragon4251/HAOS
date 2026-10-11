import io

from PIL import Image
import pytest

from haos.application_session import jpeg_capture


def png(size=(80,60),color=(10,30,80)):
    output=io.BytesIO();Image.new('RGB',size,color).save(output,format='PNG')
    return output.getvalue()


def test_grim_png_is_encoded_as_a_real_jpeg_without_optional_grim_jpeg_support():
    data=jpeg_capture(png())
    assert data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')
    with Image.open(io.BytesIO(data)) as frame:
        assert frame.format=='JPEG' and frame.size==(80,60)
        assert max(abs(v-w) for v,w in zip(frame.getpixel((40,30)),(10,30,80)))<5
        assert not frame.getexif()


@pytest.mark.parametrize('encoded',[b'not a compositor PNG',b'\x89PNG\r\n\x1a\n'+b'x'*(8*1024*1024),png((2049,1)),png((1,2049))])
def test_unbounded_malformed_or_overdimension_capture_is_rejected(encoded):
    with pytest.raises(ValueError):jpeg_capture(encoded)
