from __future__ import annotations

import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document as DocxDocument
from docx.table import Table
from pypdf import PdfReader

from job_apply_pro.domain.knowledge import DocumentExtraction, LayoutBlock

MAX_CHARACTERS = 200_000
MAX_BLOCKS = 5_000
MAX_PAGES = 500
MIN_MEANINGFUL_PAGE_CHARACTERS = 10
MAX_DOCX_ARCHIVE_ENTRIES = 10_000
MAX_DOCX_EXPANDED_BYTES = 52_428_800
MAX_DOCX_SINGLE_ENTRY_BYTES = 20_971_520
MAX_OCR_PAGE_PIXELS = 25_000_000
MAX_OCR_PAGE_OUTPUT_BYTES = 80_000
MAX_PDF_PAGE_CONTENT_BYTES = 20_971_520
PDF_COLUMN_GAP_CHARACTERS = 4
PDF_MIN_COLUMN_SEPARATION = 12
PDF_MIN_MULTI_COLUMN_ROWS = 2
HELPER_INHERITED_ENVIRONMENT = {
    "COMSPEC",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMROOT",
    "TESSDATA_PREFIX",
    "WINDIR",
}


@dataclass(frozen=True)
class DocumentIngestionOptions:
    legacy_doc_converter_path: Path | None = None
    legacy_doc_conversion_timeout_seconds: int = 30
    max_converted_bytes: int = 10_485_760
    ocr_enabled: bool = False
    ocr_tesseract_path: Path | None = None
    ocr_language: str = "eng"
    ocr_dpi: int = 200
    ocr_max_pages: int = 25
    ocr_page_timeout_seconds: int = 30


class DocumentExtractionError(ValueError):
    pass


class UnsupportedDocumentError(DocumentExtractionError):
    pass


def _bounded(
    blocks: list[LayoutBlock],
    parser: str,
    page_count: int,
    warnings: list[str] | None = None,
) -> DocumentExtraction:
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
        warnings=(warnings or [])[:100],
    )


def _trusted_executable(path: Path | None, allowed_names: set[str], label: str) -> Path:
    if path is None:
        raise DocumentExtractionError(f"{label} executable is not configured")
    if not path.is_absolute():
        raise DocumentExtractionError(f"{label} executable path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise DocumentExtractionError(f"{label} executable was not found") from error
    if not resolved.is_file() or resolved.name.casefold() not in allowed_names:
        raise DocumentExtractionError(f"{label} executable path is not an approved executable")
    return resolved


def _run_process(
    command: list[str], *, cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name in HELPER_INHERITED_ENVIRONMENT
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "APPDATA": str(cwd),
            "HOME": str(cwd),
            "LOCALAPPDATA": str(cwd),
            "TEMP": str(cwd),
            "TMP": str(cwd),
            "USERPROFILE": str(cwd),
        }
    )
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise DocumentExtractionError("Document helper process timed out") from error
    except OSError as error:
        raise DocumentExtractionError("Document helper process could not start") from error


def _ocr_pdf_pages(
    data: bytes,
    page_indexes: list[int],
    options: DocumentIngestionOptions,
) -> tuple[dict[int, str], list[str]]:
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,40}", options.ocr_language):
        raise DocumentExtractionError("OCR language contains unsupported characters")
    executable = _trusted_executable(
        options.ocr_tesseract_path, {"tesseract", "tesseract.exe"}, "Tesseract OCR"
    )
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - packaging guard
        raise DocumentExtractionError("PDF OCR rendering support is unavailable") from error

    extracted: dict[int, str] = {}
    warnings: list[str] = []
    try:
        document = pdfium.PdfDocument(data)
        with TemporaryDirectory(prefix="jap-ocr-") as temporary:
            temporary_path = Path(temporary)
            for page_index in page_indexes:
                page = document[page_index]
                width, height = page.get_size()
                pixel_width = ceil(width * options.ocr_dpi / 72)
                pixel_height = ceil(height * options.ocr_dpi / 72)
                if pixel_width * pixel_height > MAX_OCR_PAGE_PIXELS:
                    warnings.append(
                        f"OCR skipped PDF page {page_index + 1} because its rendered size "
                        "exceeded the safety limit"
                    )
                    page.close()
                    continue
                bitmap = page.render(scale=options.ocr_dpi / 72)
                image = bitmap.to_pil()
                image_path = temporary_path / f"page-{page_index + 1}.png"
                output_base = temporary_path / f"page-{page_index + 1}-ocr"
                output_path = output_base.with_suffix(".txt")
                try:
                    image.save(image_path, format="PNG")
                finally:
                    image.close()
                    bitmap.close()
                    page.close()
                result = _run_process(
                    [
                        str(executable),
                        str(image_path),
                        str(output_base),
                        "-l",
                        options.ocr_language,
                        "--psm",
                        "6",
                    ],
                    cwd=temporary_path,
                    timeout=options.ocr_page_timeout_seconds,
                )
                if output_path.is_file() and output_path.stat().st_size > MAX_OCR_PAGE_OUTPUT_BYTES:
                    warnings.append(f"OCR output exceeded the limit for PDF page {page_index + 1}")
                    continue
                text = (
                    output_path.read_text(encoding="utf-8", errors="replace").strip()
                    if output_path.is_file()
                    else ""
                )
                if result.returncode == 0 and len(text) >= MIN_MEANINGFUL_PAGE_CHARACTERS:
                    extracted[page_index] = text[:20_000]
                else:
                    warnings.append(
                        f"OCR did not recover meaningful text from PDF page {page_index + 1}"
                    )
    except DocumentExtractionError:
        raise
    except Exception as error:
        raise DocumentExtractionError("PDF OCR rendering failed") from error
    finally:
        if "document" in locals():
            document.close()
    return extracted, warnings


def _extract_pdf(
    data: bytes, options: DocumentIngestionOptions | None = None
) -> DocumentExtraction:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise DocumentExtractionError("Password-protected PDF files are not supported")
        if len(reader.pages) > MAX_PAGES:
            raise DocumentExtractionError(f"PDF exceeds the {MAX_PAGES}-page limit")
        page_blocks: list[list[LayoutBlock]] = []
        multi_column_pages: list[int] = []
        for page_index, page in enumerate(reader.pages):
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PDF_PAGE_CONTENT_BYTES:
                raise DocumentExtractionError(
                    f"PDF page {page_index + 1} content stream exceeds the safety limit"
                )
            extracted, multi_column = _extract_pdf_layout_page(page, page_index + 1)
            page_blocks.append(extracted)
            if multi_column:
                multi_column_pages.append(page_index + 1)
    except DocumentExtractionError:
        raise
    except Exception as error:
        raise DocumentExtractionError("PDF parsing failed") from error
    warnings: list[str] = []
    blank_pages = [
        page_index
        for page_index, page in enumerate(page_blocks)
        if len(" ".join(block.text for block in page).strip()) < MIN_MEANINGFUL_PAGE_CHARACTERS
    ]
    if blank_pages and options and options.ocr_enabled:
        selected_pages = blank_pages[: options.ocr_max_pages]
        recovered, ocr_warnings = _ocr_pdf_pages(data, selected_pages, options)
        warnings.extend(ocr_warnings)
        if len(blank_pages) > len(selected_pages):
            warnings.append(
                f"OCR page limit skipped {len(blank_pages) - len(selected_pages)} PDF page(s)"
            )
        for page_index, text in recovered.items():
            page_blocks[page_index] = [
                LayoutBlock(
                    index=0,
                    page=page_index + 1,
                    row=0,
                    kind="OCR_PAGE_TEXT",
                    style=f"tesseract:{options.ocr_language}:{options.ocr_dpi}dpi",
                    text=text,
                )
            ]
        parser = "pypdf-layout/2+tesseract/1" if recovered else "pypdf-layout/2"
    else:
        parser = "pypdf-layout/2"
        if blank_pages:
            warnings.append(
                f"{len(blank_pages)} PDF page(s) had no meaningful text; OCR was not enabled"
            )
    if multi_column_pages:
        warnings.append(
            "Layout-aware column ordering was applied to PDF page(s): "
            + ", ".join(str(page) for page in multi_column_pages)
            + "; review complex graphics or spanning content"
        )
    blocks = [
        block.model_copy(update={"index": index})
        for index, block in enumerate(block for page in page_blocks for block in page)
    ]
    try:
        return _bounded(blocks, parser, len(reader.pages), warnings)
    except DocumentExtractionError as error:
        if blank_pages and not (options and options.ocr_enabled):
            raise DocumentExtractionError(
                "The PDF did not contain extractable text; configure and enable OCR "
                "for scanned PDFs"
            ) from error
        raise


def _layout_segments(line: str) -> list[tuple[int, str]]:
    segments: list[tuple[int, str]] = []
    for match in re.finditer(
        rf"\S(?:.*?\S)?(?=\s{{{PDF_COLUMN_GAP_CHARACTERS},}}|\s*$)", line.rstrip()
    ):
        text = match.group(0).strip()
        if text:
            segments.append((match.start(), text))
    return segments


def _column_starts(rows: list[list[tuple[int, str]]]) -> list[int]:
    multi_rows = [row for row in rows if len(row) >= 2]
    if len(multi_rows) < PDF_MIN_MULTI_COLUMN_ROWS:
        return []
    starts = sorted(start for row in multi_rows for start, _ in row)
    clusters: list[list[int]] = []
    for start in starts:
        if not clusters or start - round(sum(clusters[-1]) / len(clusters[-1])) >= 4:
            clusters.append([start])
        else:
            clusters[-1].append(start)
    centers = [round(sum(cluster) / len(cluster)) for cluster in clusters if len(cluster) >= 2]
    separated = [centers[0]] if centers else []
    for center in centers[1:]:
        if center - separated[-1] >= PDF_MIN_COLUMN_SEPARATION:
            separated.append(center)
    return separated if len(separated) >= 2 else []


def _extract_pdf_layout_page(page: object, page_number: int) -> tuple[list[LayoutBlock], bool]:
    layout = (
        page.extract_text(  # type: ignore[attr-defined]
            extraction_mode="layout",
            layout_mode_space_vertically=False,
        )
        or ""
    )
    rows = [_layout_segments(line) for line in layout.splitlines() if line.strip()]
    if not rows:
        return [
            LayoutBlock(index=0, page=page_number, row=0, kind="PDF_LAYOUT_LINE", text="")
        ], False
    starts = _column_starts(rows)
    if not starts:
        return (
            [
                LayoutBlock(
                    index=0,
                    page=page_number,
                    row=row_index,
                    kind="PDF_LAYOUT_LINE",
                    text=" ".join(text for _, text in row)[:20_000],
                )
                for row_index, row in enumerate(rows)
                if row
            ],
            False,
        )

    first_multi_row = next(index for index, row in enumerate(rows) if len(row) >= 2)
    ordered: list[tuple[int, int | None, str]] = []
    for row_index, row in enumerate(rows[:first_multi_row]):
        if row:
            ordered.append((row_index, None, " ".join(text for _, text in row)))
    columns: list[list[tuple[int, str]]] = [[] for _ in starts]
    for row_index, row in enumerate(rows[first_multi_row:], start=first_multi_row):
        for start, text in row:
            column = min(range(len(starts)), key=lambda index: abs(starts[index] - start))
            columns[column].append((row_index, text))
    for column, entries in enumerate(columns):
        ordered.extend((row_index, column, text) for row_index, text in entries)
    return (
        [
            LayoutBlock(
                index=0,
                page=page_number,
                row=row,
                column=column,
                kind="PDF_LAYOUT_LINE",
                style="pypdf:layout:column-major" if column is not None else "pypdf:layout",
                text=text[:20_000],
            )
            for row, column, text in ordered
        ],
        True,
    )


def _extract_docx(data: bytes) -> DocumentExtraction:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ARCHIVE_ENTRIES:
                raise DocumentExtractionError("DOCX archive contains too many entries")
            if any(entry.file_size > MAX_DOCX_SINGLE_ENTRY_BYTES for entry in entries):
                raise DocumentExtractionError("DOCX archive entry exceeds the safety limit")
            if sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED_BYTES:
                raise DocumentExtractionError("DOCX expanded content exceeds the safety limit")
    except DocumentExtractionError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise DocumentExtractionError("DOCX archive validation failed") from error
    try:
        document = DocxDocument(BytesIO(data))
    except Exception as error:
        raise DocumentExtractionError("DOCX parsing failed") from error
    blocks: list[LayoutBlock] = []
    table_index = 0
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            for row_index, row in enumerate(item.rows):
                text = " | ".join(cell.text.strip() for cell in row.cells).strip(" |")
                if text:
                    blocks.append(
                        LayoutBlock(
                            index=len(blocks),
                            row=row_index,
                            table=table_index,
                            kind="TABLE_ROW",
                            style=f"table:{table_index}:row:{row_index}",
                            text=text[:20_000],
                        )
                    )
            table_index += 1
            continue
        text = item.text.strip()
        if text:
            blocks.append(
                LayoutBlock(
                    index=len(blocks),
                    kind="PARAGRAPH",
                    style=item.style.name[:100] if item.style else None,
                    text=text[:20_000],
                )
            )
    return _bounded(blocks, "python-docx-layout/2", 1)


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


def _extract_legacy_doc(data: bytes, options: DocumentIngestionOptions) -> DocumentExtraction:
    executable = _trusted_executable(
        options.legacy_doc_converter_path,
        {"soffice", "soffice.exe", "soffice.com"},
        "LibreOffice converter",
    )
    with TemporaryDirectory(prefix="jap-doc-convert-") as temporary:
        temporary_path = Path(temporary)
        profile_path = temporary_path / "profile"
        profile_path.mkdir()
        source_path = temporary_path / "source.doc"
        output_path = temporary_path / "source.docx"
        source_path.write_bytes(data)
        result = _run_process(
            [
                str(executable),
                f"-env:UserInstallation={profile_path.as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "docx",
                "--outdir",
                str(temporary_path),
                str(source_path),
            ],
            cwd=temporary_path,
            timeout=options.legacy_doc_conversion_timeout_seconds,
        )
        if result.returncode != 0 or not output_path.is_file():
            raise DocumentExtractionError("Legacy DOC conversion failed")
        converted = output_path.read_bytes()
        if not converted or len(converted) > options.max_converted_bytes:
            raise DocumentExtractionError(
                "Converted DOCX output was empty or exceeded safety limits"
            )
    extraction = _extract_docx(converted)
    return extraction.model_copy(
        update={
            "parser": f"libreoffice-doc-to-docx/1+{extraction.parser}",
            "warnings": [
                "Legacy DOC content was converted in an isolated temporary workspace before parsing"
            ],
        }
    )


def extract_document(
    file_name: str,
    data: bytes,
    options: DocumentIngestionOptions | None = None,
) -> tuple[str, DocumentExtraction]:
    ingestion = options or DocumentIngestionOptions()
    suffix = Path(file_name).suffix.casefold()
    if suffix == ".pdf":
        return "application/pdf", _extract_pdf(data, ingestion)
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
        if ingestion.legacy_doc_converter_path is None:
            raise UnsupportedDocumentError(
                "Legacy DOC import requires an explicitly configured LibreOffice executable"
            )
        return "application/msword", _extract_legacy_doc(data, ingestion)
    raise UnsupportedDocumentError(
        "Supported document formats are DOC, DOCX, PDF, RTF, TXT, and Markdown"
    )
