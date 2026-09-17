from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from app.domain.documents import DocumentFailureCode, DocumentFormat
from app.services.document_parsing import DocumentParseError, DocumentParser


def _xlsx_fixture() -> bytes:
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="FAQ" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>问题</t></is></c><c r="B1" t="inlineStr"><is><t>答案</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>如何登录？</t></is></c><c r="B2" t="inlineStr"><is><t>使用邮箱登录。</t></is></c></row>'
        '</sheetData></worksheet>'
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def test_xlsx_parser_extracts_faq_rows() -> None:
    document = DocumentParser().parse(filename="faq.xlsx", content=_xlsx_fixture())

    assert document.format is DocumentFormat.TABLE
    assert len(document.blocks) == 1
    assert document.blocks[0].heading_path == ("FAQ",)
    assert "问题：如何登录？" in document.blocks[0].text
    assert "答案：使用邮箱登录。" in document.blocks[0].text


def test_malformed_xlsx_is_reported_as_a_safe_parse_failure() -> None:
    with pytest.raises(DocumentParseError) as error:
        DocumentParser().parse(filename="faq.xlsx", content=b"not an xlsx")

    assert error.value.code is DocumentFailureCode.MALFORMED_DOCUMENT


def test_image_only_pdf_has_a_scanned_document_error_code() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    image = DecodedStreamObject()
    image.set_data(b"\x00\x00\x00")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})}
    )
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(DocumentParseError) as error:
        DocumentParser().parse(filename="scan.pdf", content=buffer.getvalue())

    assert error.value.code is DocumentFailureCode.SCANNED_DOCUMENT
