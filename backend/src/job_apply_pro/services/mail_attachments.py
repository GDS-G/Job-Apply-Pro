from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from job_apply_pro.domain.communications import MailAttachmentManifest, MailAttachmentMetadata
from job_apply_pro.domain.knowledge import DocumentKind
from job_apply_pro.domain.mail import (
    MAX_MAIL_ATTACHMENT_BYTES,
    MAX_MAIL_ATTACHMENTS,
    MailAttachmentError,
    VerifiedMailAttachment,
    validate_attachment_bytes,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.storage.repository_contracts import (
    CandidateKnowledgeRepositoryProtocol,
    WorkbenchRepositoryProtocol,
)


class MailAttachmentResolver:
    def __init__(
        self,
        knowledge: CandidateKnowledgeRepositoryProtocol,
        workflows: WorkbenchRepositoryProtocol,
        cipher: SensitiveDataCipher,
        document_data_dir: Path,
    ) -> None:
        self._knowledge = knowledge
        self._workflows = workflows
        self._cipher = cipher
        self._root = document_data_dir.resolve()

    def resolve(
        self, workflow_id: str | None, version_ids: list[str]
    ) -> tuple[MailAttachmentManifest, tuple[VerifiedMailAttachment, ...]]:
        try:
            return self._resolve(workflow_id, version_ids)
        except MailAttachmentError:
            raise
        except (ValueError, OSError, RuntimeError, KeyConfigurationError) as error:
            # Malformed stored metadata must not expose validation inputs through the API.
            raise MailAttachmentError("The selected document could not be verified") from error

    def _resolve(
        self, workflow_id: str | None, version_ids: list[str]
    ) -> tuple[MailAttachmentManifest, tuple[VerifiedMailAttachment, ...]]:
        if not workflow_id:
            raise MailAttachmentError(
                "Document attachments require a selected application workflow"
            )
        if not 1 <= len(version_ids) <= MAX_MAIL_ATTACHMENTS or len(set(version_ids)) != len(
            version_ids
        ):
            raise MailAttachmentError("Select between one and four unique document versions")
        workflow = self._workflows.get_snapshot(workflow_id)
        if workflow is None:
            raise MailAttachmentError("The selected application workflow is unavailable")
        attachments: list[VerifiedMailAttachment] = []
        total = 0
        for version_id in version_ids:
            version = self._knowledge.get_version_record(version_id)
            document = self._knowledge.get_document(version.document_id) if version else None
            if (
                version is None
                or document is None
                or document.profile_id != workflow.profile_id
                or document.archived
                or document.kind
                not in {
                    DocumentKind.RESUME,
                    DocumentKind.COVER_LETTER,
                    DocumentKind.CERTIFICATION,
                    DocumentKind.EDUCATION,
                    DocumentKind.PORTFOLIO,
                }
            ):
                raise MailAttachmentError("The selected document is unavailable for this workflow")
            try:
                path = Path(version.storage_path).resolve(strict=True)
                if not path.is_relative_to(self._root):
                    raise MailAttachmentError("The selected document storage is unavailable")
                # Ciphertext is base64 plus a fixed envelope; bound it before decryption.
                maximum = ((MAX_MAIL_ATTACHMENT_BYTES + 64) * 4 // 3) + 256
                with path.open("rb") as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise MailAttachmentError("The selected document storage is unavailable")
                    encrypted = source.read(maximum + 1)
                if len(encrypted) > maximum:
                    raise MailAttachmentError("Attachments exceed the 2 MiB combined size limit")
                data = self._cipher.decrypt_bytes(
                    encrypted.decode("ascii"), context=f"document:{version.id}:file"
                )
            except MailAttachmentError:
                raise
            except (OSError, ValueError, UnicodeError, KeyConfigurationError) as error:
                raise MailAttachmentError("The selected document could not be verified") from error
            total += len(data)
            if not data or total > MAX_MAIL_ATTACHMENT_BYTES:
                raise MailAttachmentError("Attachments exceed the 2 MiB combined size limit")
            if hashlib.sha256(data).hexdigest() != version.sha256:
                raise MailAttachmentError("Attachment content does not match its stored version")
            attachment = VerifiedMailAttachment(
                metadata=MailAttachmentMetadata(
                    document_version_id=version.id,
                    document_id=document.id,
                    file_name=version.file_name,
                    media_type=version.media_type,
                    sha256=version.sha256,
                    size_bytes=len(data),
                ),
                data=data,
            )
            validate_attachment_bytes(attachment)
            attachments.append(attachment)
        return (
            MailAttachmentManifest(
                profile_id=workflow.profile_id,
                attachments=tuple(item.metadata for item in attachments),
            ),
            tuple(attachments),
        )
