"""A tiny PDF writer for the document tests: text pages in the standard Helvetica fonts and
image-only pages (a JPEG per page, the way scanners write them). No third-party packages."""

from __future__ import annotations

from typing import Sequence

# One line of text: (x, y, font size, text); a size below zero selects the bold face.
Line = tuple[float, float, float, str]


def _escape(text: str) -> bytes:
    data = text.replace("€", "\x80").encode("latin-1", errors="replace")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _stream(dictionary: str, data: bytes) -> bytes:
    return f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def assemble(objects: Sequence[bytes]) -> bytes:
    """Number the objects from 1 in order and write the xref table and trailer (object 1 is the catalog)."""
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def text_pdf(pages: Sequence[Sequence[Line]], size: tuple[float, float] = (612, 792)) -> bytes:
    """A PDF with a real text layer: each page is a list of lines."""
    width, height = size
    first_page = 5
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(len(pages)))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    for index, lines in enumerate(pages):
        content = b"".join(
            b"BT /F%d %g Tf %g %g Td (" % (2 if size_ < 0 else 1, abs(size_), x, y) + _escape(text) + b") Tj ET\n"
            for x, y, size_, text in lines
        )
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:g} {height:g}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {first_page + 2 * index + 1} 0 R >>".encode())
        objects.append(_stream("", content))
    return assemble(objects)


def image_pdf(images: Sequence[tuple[bytes, int, int]], size: tuple[float, float] = (612, 792)) -> bytes:
    """A PDF whose pages are only pictures: (JPEG bytes, pixel width, pixel height) per page."""
    width, height = size
    first_page = 3
    kids = " ".join(f"{first_page + 3 * i} 0 R" for i in range(len(images)))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(images)} >>".encode(),
    ]
    for index, (jpeg, pixels_w, pixels_h) in enumerate(images):
        page = first_page + 3 * index
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:g} {height:g}] /Resources << /XObject << /Im0 {page + 2} 0 R >> >> /Contents {page + 1} 0 R >>".encode())
        objects.append(_stream("", f"q {width:g} 0 0 {height:g} 0 0 cm /Im0 Do Q".encode()))
        objects.append(_stream(f"/Type /XObject /Subtype /Image /Width {pixels_w} /Height {pixels_h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode", jpeg))
    return assemble(objects)
