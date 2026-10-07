"""``system_documents``: the hints read from a document's text, the PDF helpers, the filing places, the
tool itself (with a fake host, and on macOS with PDFKit and Vision) and the Linux text and OCR chain."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from pdf_fixtures import assemble, image_pdf, text_pdf


def _mod(plugin, name):
    return importlib.import_module(plugin.__name__ + ".bridge." + name)


ACME = """Acme Corp
100 Market Street, Springfield
billing@acmecorp.example
TAX INVOICE
Invoice Number: INV-1234
Invoice Date: 14 September 2026
Due Date: 14 October 2026
Bill To
Sam Example
42 Sample Road, Springfield
Description Qty Amount
Website maintenance, September 1 $500.00
Subtotal $509.09
Tax (10%) $50.91
Total Due $560.00
"""

BLUEBIRD = """ABN 12 345 678 901 Bluebird Design Studio Pty Ltd
7 Harbour Lane, Sydney NSW 2000
INVOICE
Invoice # 2026-0915
Date: 03/09/2026
Client: Example Holdings
Logo refresh and brand guide 1,122.27
Amount due (AUD) AUD 1,234.50
"""

STATEMENT = """Example Bank
Account statement
Statement period: 1 August 2026 to 31 August 2026
Opening balance $2,000.00
12 Aug  Acme Corp  -$560.00
Closing balance $4,540.00
"""

RECIPE = "Banana Bread\nIngredients: 3 ripe bananas, 2 cups flour, 1 cup sugar.\nBake at 180 degrees for 60 minutes.\n"


# ---------------------------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------------------------

def test_detect_fields_reads_an_invoice(plugin):
    docs = _mod(plugin, "documents")
    hints = docs.detect_fields(ACME)
    assert (hints["kind"], hints["confidence"]) == ("invoice", "high")
    assert hints["vendor"] == "Acme Corp", "the e-mail domain backs the first line"
    assert "Sam Example" not in hints["vendor_candidates"], "the bill-to block is the customer"
    assert (hints["date"], hints["due_date"], hints["number"]) == ("2026-09-14", "2026-10-14", "INV-1234")
    assert hints["total"] == {"amount": "560.00", "currency": "$", "text": "$560.00", "formatted": "$560.00"}
    assert docs.suggest_name(hints, ".PDF") == "2026-09-14 Acme Corp invoice INV-1234 $560.00.pdf"


def test_company_on_a_shared_line_and_ambiguous_dates(plugin):
    docs = _mod(plugin, "documents")
    hints = docs.detect_fields(BLUEBIRD)
    assert hints["vendor"] == "Bluebird Design Studio Pty Ltd", "the ABN in front of the name is dropped"
    assert hints["date"] == "2026-09-03" and hints["date_ambiguous"] is True
    assert hints["total"]["formatted"] == "AUD 1,234.50" and hints["currency"] == "AUD"
    assert docs.suggest_name(hints, ".pdf") == "2026-09-03 Bluebird Design Studio invoice 2026-0915 AUD 1,234.50.pdf"


def test_classify_tells_documents_apart(plugin):
    docs = _mod(plugin, "documents")
    assert docs.classify(STATEMENT)[0] == "statement"
    assert docs.classify("Coffee Corner\nReceipt #4471\nTOTAL $8.50\nPaid by card.")[:2] == ("receipt", "high")
    assert docs.classify(RECIPE) == ("other", "low", [])
    statement = docs.detect_fields(STATEMENT)
    assert statement["date"] == "2026-08-31", "a statement is known by the end of its period"
    assert docs.suggest_name(statement, ".pdf") == "2026-08-31 Example Bank statement.pdf", "statements carry no amount"
    assert docs.suggest_name(docs.detect_fields(RECIPE), ".pdf") is None


def test_find_dates_formats_and_labels(plugin):
    docs = _mod(plugin, "documents")
    found = docs.find_dates("Invoice date 2026-08-28\nPayable by 27.09.2026\nIssued September 5, 2026\nOrder 7 Oct 2026")
    assert [(d["date"], d["label"]) for d in found] == [("2026-08-28", "issued"), ("2026-09-27", "due"), ("2026-09-05", "issued"), ("2026-10-07", "")]
    assert docs.find_dates("Date: 09/14/2026")[0]["date"] == "2026-09-14", "a month cannot be 14"
    assert docs.find_dates("Date: 03/09/2026")[0] == {"date": "2026-09-03", "text": "03/09/2026", "label": "issued", "ambiguous": True}
    assert docs.find_dates("Date: 03/09/2026 Total USD 5.00")[0]["date"] == "2026-03-09", "American documents read month first"
    assert docs.find_dates("Due\n14 October 2026")[0]["label"] == "due", "a label on the line above counts"
    assert docs.find_dates("Version 31/02/2026 and 1999-13-40") == []


def test_amounts_totals_and_numbers(plugin):
    docs = _mod(plugin, "documents")
    assert [docs.parse_number(n) for n in ("1,234.56", "1.234,56", "1 234,56", "89,90", "560")] == [docs.Decimal("1234.56"), docs.Decimal("1234.56"), docs.Decimal("1234.56"), docs.Decimal("89.90"), docs.Decimal("560")]
    amounts = docs.find_amounts("Net amount EUR 75,55\nVAT 19% EUR 14,35\nTotal EUR 89,90")
    assert [(a["amount"], a["currency"], a["label"]) for a in amounts] == [("75.55", "EUR", "subtotal"), ("14.35", "EUR", "tax"), ("89.90", "EUR", "total")]
    assert docs.pick_total(amounts)["formatted"] == "EUR 89.90"
    paid = docs.find_amounts("Total $560.00\nAmount due $0.00")
    assert docs.pick_total(paid)["amount"] == "560.00", "a paid invoice keeps its total"
    same_line = docs.find_amounts("Subtotal $509.09 Tax $50.91 Total $560.00")
    assert [a["label"] for a in same_line] == ["subtotal", "tax", "total"]
    assert docs.find_amounts("Qty 19% and 2 pages") == []
    numbers = docs.find_numbers("Invoice # 2026-0915\nInvoice no. NL-77812\nReceipt #4471\nInvoice Date: 14 September 2026\nInvoice 2026\nPO Box 12")
    assert [n["value"] for n in numbers] == ["2026-0915", "NL-77812", "4471"]


def test_names_are_safe_and_short(plugin):
    docs = _mod(plugin, "documents")
    assert docs.safe_filename('a/b: c*d?  "e" ') == "a-b- c-d- -e-"
    assert docs.short_vendor("Nordlicht GmbH") == "Nordlicht" and docs.short_vendor("Acme Corp") == "Acme Corp"
    assert docs.format_money(docs.Decimal("1234.5"), "€") == "€1,234.50"
    hints = {"kind": "invoice", "vendor": "Bob/Sons Pty Ltd", "date": None, "number": "A:1", "total": None}
    assert docs.suggest_name(hints, ".pdf") == "Bob-Sons invoice A-1.pdf"
    assert docs.suggest_name({"kind": "invoice", "vendor": None, "date": None}, ".pdf") is None


# ---------------------------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------------------------

def test_pdftotext_pages_and_page_count(plugin):
    docs = _mod(plugin, "documents")
    assert docs.split_pdftotext("one\fpage two\f\f") == ["one", "page two", ""]
    pdf = text_pdf([[(72, 700, 12, "first")], [(72, 700, 12, "second")]])
    assert docs.count_pdf_pages(pdf) == 2


def _grey_image_pdf(width: int, height: int, predictor: bool) -> tuple[bytes, bytes]:
    """A PDF whose page is an 8-bit grey Flate image (optionally with PNG ``Up`` row prediction)."""
    pixels = bytes((x * 7 + y) % 256 for y in range(height) for x in range(width))
    raw = pixels
    if predictor:
        # Each row stored as its difference from the row above, after the "Up" filter byte (2).
        rows, previous = [], bytes(width)
        for y in range(height):
            row = pixels[y * width:(y + 1) * width]
            rows.append(b"\x02" + bytes((a - b) % 256 for a, b in zip(row, previous)))
            previous = row
        raw = b"".join(rows)
    data = zlib.compress(raw)
    parms = f" /DecodeParms << /Predictor 12 /Colors 1 /Columns {width} >>" if predictor else ""
    image = f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode{parms} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 30 >>\nstream\nq 612 0 0 792 0 0 cm /Im0 Do Q\nendstream",
        image,
    ]
    return assemble(objects), pixels


def test_page_images_unpacks_the_pictures_of_a_scan(plugin):
    docs = _mod(plugin, "documents")
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"
    pictures = docs.page_images(image_pdf([(jpeg, 1240, 1754), (jpeg + b"2", 1240, 1754)]), limit=5)
    assert [(p.extension, p.data, p.width) for p in pictures] == [(".jpg", jpeg, 1240), (".jpg", jpeg + b"2", 1240)]
    assert len(docs.page_images(image_pdf([(jpeg, 1240, 1754)] * 3), limit=2)) == 2
    assert docs.page_images(image_pdf([(jpeg, 120, 60)]), limit=5) == [], "logos and icons are not pages"
    for predictor in (False, True):
        pdf, pixels = _grey_image_pdf(240, 220, predictor)
        (grey,) = docs.page_images(pdf, limit=5)
        assert grey.extension == ".pgm" and grey.data == b"P5\n240 220\n255\n" + pixels


def test_ccitt_fax_data_is_wrapped_in_a_tiff(plugin):
    docs = _mod(plugin, "documents")
    import struct

    tiff = docs.ccitt_tiff(b"FAXDATA", 2480, 3508, -1, False)
    assert tiff[:4] == b"II*\x00" and tiff.endswith(b"FAXDATA")
    count = struct.unpack("<H", tiff[8:10])[0]
    tags = {struct.unpack("<H", tiff[10 + 12 * i:12 + 12 * i])[0]: tiff[10 + 12 * i:22 + 12 * i] for i in range(count)}
    assert struct.unpack("<H", tags[259][8:10])[0] == 4, "K < 0 is Group 4"
    assert struct.unpack("<H", tags[262][8:10])[0] == 0, "black runs drawn black"
    assert struct.unpack("<I", tags[273][8:12])[0] == len(tiff) - len(b"FAXDATA"), "the strip follows the header"


# ---------------------------------------------------------------------------------------------
# Which files, and where documents are filed
# ---------------------------------------------------------------------------------------------

def test_collect_documents_from_folders_and_files(plugin, tmp_path):
    docs = _mod(plugin, "documents")
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for index, name in enumerate(["old.pdf", "photo.JPG", "notes.txt", ".hidden.pdf", "new.pdf"]):
        (folder / name).write_bytes(b"%PDF")
        os.utime(folder / name, (1_000_000 + index, 1_000_000 + index))
    (folder / "sub").mkdir()
    (folder / "sub" / "deep.pdf").write_bytes(b"%PDF")
    files, skipped = docs.collect_documents([folder, folder / "notes.txt", tmp_path / "gone.pdf"], limit=10)
    assert [f.name for f in files] == ["new.pdf", "photo.JPG", "old.pdf"], "newest first, no hidden files, not recursive"
    assert {s["reason"].split(";")[0] for s in skipped} == {"not a PDF or an image", "does not exist"}
    few, rest = docs.collect_documents([folder], limit=2)
    assert len(few) == 2 and rest[0]["path"].endswith("old.pdf")


def test_find_places_describes_filing_folders(plugin, tmp_path):
    docs = _mod(plugin, "documents")
    documents = tmp_path / "Documents"
    for year in ("2025", "2026"):
        (documents / "Finances" / "Invoices" / year).mkdir(parents=True)
    filed = documents / "Finances" / "Invoices" / "2026" / "2026-08-02 Telstra invoice 9921 $89.00.pdf"
    filed.write_bytes(b"%PDF")
    (documents / "Finances" / "Receipts").mkdir()
    (documents / "Taxes.app" / "Invoices").mkdir(parents=True)
    (documents / "Private" / "Bills").mkdir(parents=True)
    (tmp_path / "Library" / "Invoices").mkdir(parents=True)
    result = docs.find_places([(documents, 3), (tmp_path, 1)], skip=lambda p: p.name == "Private")
    places = {Path(p["path"]).relative_to(tmp_path).as_posix(): p for p in result["places"]}
    assert set(places) == {"Documents/Finances", "Documents/Finances/Invoices", "Documents/Finances/Receipts"}
    assert places["Documents/Finances/Invoices"]["layout"] == "by year"
    assert places["Documents/Finances/Invoices"]["samples"] == ["2026/2026-08-02 Telstra invoice 9921 $89.00.pdf"]
    assert places["Documents/Finances"]["layout"] == "by vendor or topic" and places["Documents/Finances/Receipts"]["layout"] == "flat"
    assert result["note"] is None
    assert "ask the person" in docs.find_places([(tmp_path / "Documents" / "Private", 2)], skip=lambda p: p.name == "Bills")["note"]


def test_default_roots_follow_xdg_user_dirs(plugin, tmp_path):
    docs = _mod(plugin, "documents")
    assert docs.parse_user_dirs('XDG_DOCUMENTS_DIR="$HOME/Dokumente"\nXDG_DESKTOP_DIR="$HOME/Schreibtisch"\n', tmp_path) == {"documents": tmp_path / "Dokumente", "desktop": tmp_path / "Schreibtisch"}
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Dokumente"\n')
    (tmp_path / "Dokumente").mkdir()
    (tmp_path / "Dropbox").mkdir()
    (tmp_path / "Library" / "CloudStorage" / "GoogleDrive-sam").mkdir(parents=True)
    assert docs.default_roots(tmp_path) == [(tmp_path / "Dokumente", 3), (tmp_path / "Dropbox", 3), (tmp_path / "Library" / "CloudStorage" / "GoogleDrive-sam", 3), (tmp_path, 1)]


# ---------------------------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------------------------

class FakeHost:
    platform = "test"

    def __init__(self, texts: dict[str, object], docs):
        self.texts, self.docs, self.calls = texts, docs, []

    def read_document(self, path, max_pages, ocr):
        self.calls.append((path.name, max_pages, ocr))
        value = self.texts[path.name]
        if isinstance(value, Exception):
            raise value
        return self.docs.DocumentText(pages=list(value), page_count=len(value), ocr_pages=[1] if path.suffix == ".jpg" else [], engine="fake")


def test_system_documents_reads_a_folder(plugin, tmp_path, monkeypatch, isolated_home):
    tools, docs = _mod(plugin, "tools"), _mod(plugin, "documents")
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name in ("scan0001.pdf", "scan0002.pdf"):
        (folder / name).write_bytes(b"%PDF-acme")
    (folder / "document(3).pdf").write_bytes(b"%PDF-bluebird")
    (folder / "IMG_2231.jpg").write_bytes(b"jpeg")
    (folder / "broken.pdf").write_bytes(b"%PDF-broken")
    (folder / "readme.txt").write_text("not a document")
    fake = FakeHost({"scan0001.pdf": [ACME], "scan0002.pdf": [ACME], "document(3).pdf": [BLUEBIRD], "IMG_2231.jpg": ["Coffee Corner\nReceipt #4471\nTOTAL $8.50"], "broken.pdf": RuntimeError("not a readable PDF")}, docs)
    monkeypatch.setattr(tools, "host", lambda: fake)
    result = json.loads(tools.handle_system_documents({"action": "read", "path": str(folder), "ocr": "false"}))
    assert result["success"] and result["count"] == 5
    by_name = {d["name"]: d for d in result["documents"]}
    assert by_name["scan0001.pdf"]["suggested_name"] == "2026-09-14 Acme Corp invoice INV-1234 $560.00.pdf"
    assert by_name["scan0001.pdf"]["text"].startswith("--- page 1 ---\nAcme Corp") and len(by_name["scan0001.pdf"]["text"]) <= 800
    assert by_name["IMG_2231.jpg"]["hints"]["kind"] == "receipt" and by_name["IMG_2231.jpg"]["ocr_pages"] == [1]
    assert by_name["broken.pdf"]["error"] == "not a readable PDF" and "hints" not in by_name["broken.pdf"]
    assert sorted(Path(p).name for p in result["duplicates"][0]) == ["scan0001.pdf", "scan0002.pdf"]
    assert result["skipped"] == [], "a folder read only looks at PDFs and images"
    assert all(call[2] is False for call in fake.calls), "ocr=false reaches the host"
    entry = json.loads((isolated_home / "herald-os" / "audit.jsonl").read_text().strip().splitlines()[-1])
    assert entry["tool"] == "system_documents" and entry["tier"] == "read" and "Acme" not in json.dumps(entry), "no document text in the audit log"


def test_a_big_folder_reads_the_newest_and_summarises_the_rest(plugin, tmp_path, monkeypatch):
    tools, docs = _mod(plugin, "tools"), _mod(plugin, "documents")
    for index in range(40):
        path = tmp_path / f"scan{index:04d}.pdf"
        path.write_bytes(b"%PDF-" + str(index).encode())
        os.utime(path, (2_000_000 + index, 2_000_000 + index))
    fake = FakeHost({f"scan{index:04d}.pdf": [RECIPE] for index in range(40)}, docs)
    monkeypatch.setattr(tools, "host", lambda: fake)
    result = json.loads(tools.handle_system_documents({"action": "read", "path": str(tmp_path), "limit": 5}))
    assert [d["name"] for d in result["documents"]] == ["scan0039.pdf", "scan0038.pdf", "scan0037.pdf", "scan0036.pdf", "scan0035.pdf"]
    assert len(result["skipped"]) == 26 and result["skipped"][-1]["reason"].startswith("10 more not listed")


def test_system_documents_refuses_protected_paths_and_bad_input(plugin, monkeypatch):
    tools = _mod(plugin, "tools")
    monkeypatch.setattr(tools, "host", lambda: (_ for _ in ()).throw(AssertionError("nothing may be read")))
    refused = json.loads(tools.handle_system_documents({"action": "read", "paths": ["~/.ssh/id_rsa.pdf"]}))
    assert not refused["success"] and refused["decision"] == "protected"
    assert not json.loads(tools.handle_system_documents({"action": "read"}))["success"]
    assert not json.loads(tools.handle_system_documents({"action": "shred"}))["success"]


def test_system_documents_places_with_roots(plugin, tmp_path):
    tools = _mod(plugin, "tools")
    (tmp_path / "Paperwork" / "Invoices" / "2026").mkdir(parents=True)
    result = json.loads(tools.handle_system_documents({"action": "places", "roots": [str(tmp_path)]}))
    assert result["success"] and [Path(p["path"]).name for p in result["places"]] == ["Paperwork", "Invoices"]
    assert result["places"][1]["layout"] == "by year"


@pytest.mark.skipif(sys.platform != "darwin", reason="PDFKit and Vision are macOS frameworks")
def test_macos_reads_pdf_text_and_scans(plugin, tmp_path):
    darwin = _mod(plugin, "host.darwin")
    invoice = tmp_path / "scan0001.pdf"
    invoice.write_bytes(text_pdf([[(72, 700, 14, "Acme Corp"), (72, 680, 11, "Invoice Number: INV-1234")], [(72, 700, 11, "Total Due $560.00")]]))
    doc = darwin.DarwinHost().read_document(invoice, 1, True)
    assert doc.page_count == 2 and len(doc.pages) == 1 and "INV-1234" in doc.pages[0] and doc.ocr_pages == [] and doc.engine == "PDFKit"
    # A scan: a large text page rasterised by sips (on every Mac) and wrapped as an image-only PDF.
    scale = 150 / 72
    big = tmp_path / "big.pdf"
    big.write_bytes(text_pdf([[(72 * scale, 700 * scale, -22 * scale, "Northwind Plumbing"), (72 * scale, 660 * scale, 14 * scale, "Invoice No. NP-5521")]], size=(612 * scale, 792 * scale)))
    jpeg = tmp_path / "page.jpg"
    subprocess.run(["sips", "-s", "format", "jpeg", str(big), "--out", str(jpeg)], check=True, capture_output=True)
    sizes = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(jpeg)], check=True, capture_output=True, text=True).stdout.split()
    scan = tmp_path / "IMG_2231.pdf"
    scan.write_bytes(image_pdf([(jpeg.read_bytes(), int(sizes[sizes.index("pixelWidth:") + 1]), int(sizes[sizes.index("pixelHeight:") + 1]))]))
    ocr = darwin.DarwinHost().read_document(scan, 3, True)
    assert ocr.ocr_pages == [1] and ocr.engine == "PDFKit + Vision" and "NP-5521" in ocr.pages[0]
    assert darwin.DarwinHost().read_document(scan, 3, False).pages == [""], "no OCR when it is off"


def test_document_script_output_is_parsed(plugin):
    darwin = _mod(plugin, "host.darwin")
    doc = darwin.parse_document_output('{"count": "3", "pages": ["a", ""], "ocr": [2], "notes": ["n"]}\n', "pdf")
    assert (doc.page_count, doc.pages, doc.ocr_pages, doc.engine, doc.notes) == (3, ["a", ""], [2], "PDFKit + Vision", ["n"])
    with pytest.raises(RuntimeError, match="password"):
        darwin.parse_document_output('{"error": "the PDF is password protected"}', "pdf")
    with pytest.raises(RuntimeError):
        darwin.parse_document_output("not json", "pdf")


# ---------------------------------------------------------------------------------------------
# Linux: pdftotext, the Python readers and tesseract (no Linux tools are executed)
# ---------------------------------------------------------------------------------------------

class FakeRun:
    """Answers ``run`` like the poppler and tesseract binaries would; missing ones exit 127."""

    def __init__(self, installed: set[str], pdftotext: str = "", pages: int = 2):
        self.installed, self.pdftotext, self.pages, self.calls = installed, pdftotext, pages, []

    def __call__(self, argv, **_):
        from types import SimpleNamespace

        self.calls.append(list(argv))
        tool = argv[0]
        if tool not in self.installed:
            return SimpleNamespace(code=127, ok=False, stdout="", stderr=f"{tool}: not found")
        if tool == "pdftotext":
            return SimpleNamespace(code=0, ok=True, stdout=self.pdftotext, stderr="")
        if tool == "pdfinfo":
            return SimpleNamespace(code=0, ok=True, stdout=f"Pages:          {self.pages}\n", stderr="")
        if tool == "pdftoppm":
            Path(argv[-1] + ".png").write_bytes(b"png")
            return SimpleNamespace(code=0, ok=True, stdout="", stderr="")
        if tool == "tesseract":
            return SimpleNamespace(code=0, ok=True, stdout=f"OCR of {Path(argv[1]).name}: Invoice No. NP-5521\n", stderr="")
        raise AssertionError(argv)


def test_linux_reads_text_pages_and_ocrs_the_scanned_ones(plugin, tmp_path, monkeypatch):
    linux = _mod(plugin, "host.linux")
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(text_pdf([[(72, 700, 12, "x")], [(72, 700, 12, "y")]]))
    fake = FakeRun({"pdftotext", "pdfinfo", "pdftoppm", "tesseract"}, pdftotext="Acme Corp Invoice Number: INV-1234 and more text\f\f", pages=2)
    monkeypatch.setattr(linux, "run", fake)
    monkeypatch.setattr(linux.shutil, "which", lambda name: f"/usr/bin/{name}" if name in fake.installed else None)
    doc = linux.LinuxHost().read_document(pdf, 3, True)
    assert doc.page_count == 2 and doc.pages[0].startswith("Acme Corp") and doc.pages[1] == "OCR of page-2.png: Invoice No. NP-5521"
    assert doc.ocr_pages == [2] and doc.engine == "pdftotext + tesseract"
    assert ["pdftoppm", "-r", "200", "-gray", "-png", "-f", "2", "-l", "2", "-singlefile"] == fake.calls[2][:10]


def test_linux_without_poppler_ocrs_the_scan_pictures(plugin, tmp_path, monkeypatch):
    linux, docs = _mod(plugin, "host.linux"), _mod(plugin, "documents")
    scan = tmp_path / "IMG_2231.pdf"
    scan.write_bytes(image_pdf([(b"\xff\xd8jpeg\xff\xd9", 1240, 1754)]))
    fake = FakeRun({"tesseract"})
    monkeypatch.setattr(linux, "run", fake)
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/tesseract" if name == "tesseract" else None)
    monkeypatch.setattr(linux, "text_with_python", lambda path, max_pages: docs.DocumentText(pages=[""], page_count=1, engine="anydoc"))
    doc = linux.LinuxHost().read_document(scan, 3, True)
    assert doc.pages == ["OCR of page-1.jpg: Invoice No. NP-5521"] and doc.ocr_pages == [1] and doc.engine == "anydoc + tesseract"


def test_linux_names_the_missing_ocr_package(plugin, tmp_path, monkeypatch):
    linux, docs = _mod(plugin, "host.linux"), _mod(plugin, "documents")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(image_pdf([(b"\xff\xd8jpeg\xff\xd9", 1240, 1754)]))
    monkeypatch.setattr(linux, "run", FakeRun(set()))
    monkeypatch.setattr(linux.shutil, "which", lambda name: None)
    monkeypatch.setattr(linux, "text_with_python", lambda path, max_pages: docs.DocumentText(pages=[""], page_count=1, engine="anydoc"))
    doc = linux.LinuxHost().read_document(scan, 3, True)
    assert doc.ocr_pages == [] and "install tesseract" in doc.notes[0]
    with pytest.raises(linux.HostNotSupported, match="tesseract"):
        linux.LinuxHost().read_document(tmp_path / "photo.png", 1, True)


def test_python_reader_turns_anydoc_markdown_into_plain_lines(plugin, tmp_path, monkeypatch):
    docs = _mod(plugin, "documents")
    from types import SimpleNamespace

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(text_pdf([[(72, 700, 12, "x")]]))
    markdown = "# Acme Corp TAX INVOICE\n\n**Invoice Number:** INV-1234\n\n| Item | Amount |\n| --- | ---: |\n| Hosting | $9.09 |\n\nTotal Due $560.00\n"
    monkeypatch.setitem(sys.modules, "anydoc", SimpleNamespace(to_markdown=lambda path: markdown))
    doc = docs.text_with_python(pdf, 3)
    assert doc.engine == "anydoc" and doc.pages[0].splitlines()[0] == "Acme Corp TAX INVOICE"
    hints = docs.detect_fields(doc.pages[0])
    assert (hints["vendor"], hints["number"], hints["total"]["amount"]) == ("Acme Corp", "INV-1234", "560.00")
    assert "|" not in doc.pages[0] and "---" not in doc.pages[0]

    class NeedsOcr(Exception):
        pages, page_count = [1, 2], 2

    monkeypatch.setitem(sys.modules, "anydoc", SimpleNamespace(to_markdown=lambda path: (_ for _ in ()).throw(NeedsOcr("needs OCR"))))
    scanned = docs.text_with_python(pdf, 3)
    assert (scanned.pages, scanned.page_count) == (["", ""], 2), "a scan comes back as empty pages for OCR to fill"


def test_python_reader_without_any_library_says_what_to_install(plugin, tmp_path, monkeypatch):
    docs = _mod(plugin, "documents")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(text_pdf([[(72, 700, 12, "x")]]))
    monkeypatch.setitem(sys.modules, "anydoc", None)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(RuntimeError, match="poppler-utils"):
        docs.text_with_python(pdf, 3)


def test_tool_is_registered_and_listed_in_the_manifest(plugin):
    tools = _mod(plugin, "tools")
    names = [spec.name for spec in tools.TOOL_SPECS]
    assert "system_documents" in names
    manifest = (Path(plugin.__file__).parent / "plugin.yaml").read_text()
    assert all(f"  - {name}\n" in manifest for name in names), "plugin.yaml provides_tools lists every tool"
