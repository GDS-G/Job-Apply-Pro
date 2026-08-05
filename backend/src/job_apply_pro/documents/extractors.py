from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from job_apply_pro.domain.knowledge import DocumentExtraction, LayoutBlock

MAX_CHARACTERS = 200_000
MAX_BLOCKS = 5_000
MAX_PAGES = 500


class DocumentExtractionError(ValueError):
    pass


class UnsupportedDocumentError(DocumentExtractionError):
    pass


def _bounded(blocks: list[LayoutBlock], parser: str, page_count: int) -> DocumentExtraction:
    selected = blocks[:MAX_BLOCKS]
    plain_text = "\n".join(block.text for block in selected if block.text).strip()
    if len(plain_text) > MAX_CHARACTERS:
        plain_text = plain_text[:MAX_CHARACTERS]
    if not plain_text:
        raise DocumentExtractionError("The document did not contain extractable text")
    return DocumentExtraction(
        parser=parser,
        plain_text=plain_text,
        blocks=selected,
        page_count=max(1, page_count),
        character_count=len(plain_text),
    )


def _extract_pdf(data: bytes) -> DocumentExtraction:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise DocumentExtractionError("Password-protected PDF files are not supported")
        if len(reader.pages) > MAX_PAGES:
            raise DocumentExtractionError(f"PDF exceeds the {MAX_PAGES}-page limit")
        blocks = [
            LayoutBlock(
                index=index,
                page=index + 1,
                kind="PAGE_TEXT",
                text=(page.extract_text() or "")[:20_000],
            )
            for index, page in enumerate(reader.pages)
        ]
    except DocumentExtractionError:
        raise
    except Exception as error:
        raise DocumentExtractionError("PDF parsing failed") from error
    return _bounded(blocks, f"pypdf/{reader.metadata is not None}", len(reader.pages))


def _extract_docx(data: bytes) -> DocumentExtraction:
    try:
        document = DocxDocument(BytesIO(data))
    except Exception as error:
        raise DocumentExtractionError("DOCX parsing failed") from error
    blocks: list[LayoutBlock] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            blocks.append(
                LayoutBlock(
                    index=len(blocks),
                    kind="PARAGRAPH",
                    style=paragraph.style.name[:100] if paragraph.style else None,
                    text=text[:20_000],
                )
            )
    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            text = " | ".join(cell.text.strip() for cell in row.cells).strip(" |")
            if text:
                blocks.append(
                    LayoutBlock(
                        index=len(blocks),
                        kind="TABLE_ROW",
                        style=f"table:{table_index}:row:{row_index}",
                        text=text[:20_000],
                    )
                )
    return _bounded(blocks, "python-docx/1", 1)


def _extract_rtf(data: bytes) -> DocumentExtraction:
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"\\par[d]?\b", "\n", text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace("{", "").replace("}", "")
    blocks = [
        LayoutBlock(index=index, kind="PARAGRAPH", text=line.strip()[:20_000])
        for index, line in enumerate(text.splitlines())
        if line.strip()
    ]
    return _bounded(blocks, "rtf-text/1", 1)


def _extract_text(data: bytes) -> DocumentExtraction:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    blocks = [
        LayoutBlock(index=index, kind="LINE", text=line.strip()[:20_000])
        for index, line in enumerate(text.splitlines())
        if line.strip()
    ]
    return _bounded(blocks, "plain-text/1", 1)


def extract_document(file_name: str, data: bytes) -> tuple[str, DocumentExtraction]:
    suffix = Path(file_name).suffix.casefold()
    if suffix == ".pdf":
        return "application/pdf", _extract_pdf(data)
    if suffix == ".docx":
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _extract_docx(data),
        )
    if suffix == ".rtf":
        return "application/rtf", _extract_rtf(data)
    if suffix in {".txt", ".text", ".md"}:
        return "text/plain", _extract_text(data)
    if suffix == ".doc":
        raise UnsupportedDocumentError(
            "Legacy DOC files require trusted conversion to DOCX before import"
        )
    raise UnsupportedDocumentError(
        "Supported document formats are PDF, DOCX, RTF, TXT, and Markdown"
    )
