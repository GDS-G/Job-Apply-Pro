from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from xml.parsers import expat
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

import pypdfium2 as pdfium  # type: ignore[import-untyped]

from job_apply_pro.domain.communications import MailAttachmentMetadata, OutboundDraft

MAX_MAIL_ATTACHMENTS = 4
MAX_MAIL_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_MAIL_WIRE_BYTES = 4 * 1024 * 1024
MAIL_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class MailAttachmentError(ValueError):
    """Static, privacy-safe validation failure before a mail provider mutation."""


@dataclass(frozen=True)
class VerifiedMailAttachment:
    metadata: MailAttachmentMetadata
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ProviderMailResult:
    """Provider acceptance is not a guarantee of recipient delivery."""

    provider_resource_id: str | None = None


def _validate_docx_xml(data: bytes, *, content_types: bool) -> None:
    parser = expat.ParserCreate(namespace_separator="}")
    root: str | None = None
    main_type = False
    body = False

    def reject(*args: object) -> None:
        raise ValueError("DTD and entity declarations are not permitted")

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal root, main_type, body
        if root is None:
            root = name
        if content_types:
            value = attributes.get("ContentType", "").casefold()
            if "macroenabled" in value or "vbaproject" in value:
                raise ValueError("Macro-enabled content is not permitted")
            if attributes.get("PartName") == "/word/document.xml":
                main_type = value == (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                )
        elif name == "http://schemas.openxmlformats.org/wordprocessingml/2006/main}body":
            body = True

    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = lambda *args: 0
    parser.StartElementHandler = start
    parser.Parse(data, True)
    expected = (
        "http://schemas.openxmlformats.org/package/2006/content-types}Types"
        if content_types
        else "http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
    )
    if root != expected or (not main_type if content_types else not body):
        raise ValueError("Required DOCX XML structure is missing")


def validate_attachment_bytes(attachment: VerifiedMailAttachment) -> None:
    metadata, data = attachment.metadata, attachment.data
    name = metadata.file_name
    suffix = "." + name.rsplit(".", 1)[-1].lower()
    if (
        not name
        or len(name) > 200
        or any(ord(char) < 32 or ord(char) == 127 or char in "/\\:" for char in name)
        or name != name.strip()
        or suffix not in MAIL_MEDIA_TYPES
        or metadata.media_type != MAIL_MEDIA_TYPES[suffix]
    ):
        raise MailAttachmentError("Attachment filename or media type is not supported")
    if (
        not isinstance(data, bytes)
        or not 0 < len(data) <= MAX_MAIL_ATTACHMENT_BYTES
        or len(data) != metadata.size_bytes
        or hashlib.sha256(data).hexdigest() != metadata.sha256
    ):
        raise MailAttachmentError("Attachment content does not match its reviewed version")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise MailAttachmentError("Attachment content does not match its media type")
        try:
            with pdfium.PdfDocument(data) as document:
                if not 1 <= len(document) <= 100:
                    raise ValueError("Unsupported PDF page count")
        except (pdfium.PdfiumError, ValueError, OSError) as error:
            raise MailAttachmentError("Attachment is not a supported PDF document") from error
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                normalized = [name.casefold().rstrip("/") for name in names]
                if (
                    len(entries) > 2_000
                    or len(names) != len(set(names))
                    or "[Content_Types].xml" not in names
                    or "word/document.xml" not in names
                    or any(entry.flag_bits & 1 for entry in entries)
                    or any(
                        entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED} for entry in entries
                    )
                    or len(normalized) != len(set(normalized))
                    or any(
                        name.startswith("/")
                        or "\\" in name
                        or ":" in name
                        or any(part in {".", "..", ""} for part in name.rstrip("/").split("/"))
                        for name in names
                    )
                    or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024
                    or any("vbaproject" in name.casefold() for name in names)
                ):
                    raise MailAttachmentError("Attachment is not a supported DOCX document")
                expanded = 0
                for entry in entries:
                    if entry.file_size > 8 * 1024 * 1024:
                        raise ValueError("DOCX entry exceeds the supported size")
                    with archive.open(entry) as source:
                        actual = source.read(8 * 1024 * 1024 + 1)
                    expanded += len(actual)
                    if len(actual) != entry.file_size or expanded > 32 * 1024 * 1024:
                        raise ValueError("DOCX expansion exceeds the supported size")
                    if entry.filename in {"[Content_Types].xml", "word/document.xml"}:
                        _validate_docx_xml(
                            actual, content_types=entry.filename == "[Content_Types].xml"
                        )
        except (
            BadZipFile,
            OSError,
            ValueError,
            RuntimeError,
            EOFError,
            zlib.error,
            expat.ExpatError,
        ) as error:
            raise MailAttachmentError("Attachment is not a supported DOCX document") from error


def validate_mail_bundle(
    draft: OutboundDraft, attachments: tuple[VerifiedMailAttachment, ...]
) -> None:
    selected = draft.document_version_ids
    if not selected:
        if attachments or draft.attachment_manifest is not None:
            raise MailAttachmentError("Unreviewed attachments cannot be sent")
        return
    manifest = draft.attachment_manifest
    if (
        manifest is None
        or not draft.workflow_id
        or not 1 <= len(selected) <= MAX_MAIL_ATTACHMENTS
        or len(set(selected)) != len(selected)
        or not isinstance(attachments, tuple)
        or [item.metadata.document_version_id for item in attachments] != selected
        or tuple(item.metadata for item in attachments) != manifest.attachments
    ):
        raise MailAttachmentError("Attachments require a current verified document review")
    if sum(len(item.data) for item in attachments) > MAX_MAIL_ATTACHMENT_BYTES:
        raise MailAttachmentError("Attachments exceed the 2 MiB combined size limit")
    for item in attachments:
        validate_attachment_bytes(item)
