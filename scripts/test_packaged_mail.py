"""Probe frozen attachment review and send admission with providers disabled.

Uses only the standard library, synthetic in-memory PDF/DOCX files and an
isolated loopback API. This is not a live mail/provider acceptance test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


def _pdf() -> bytes:
    stream = b"BT /F1 12 Tf 72 720 Td (Synthetic mail attachment fixture) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def _docx() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Synthetic mail attachment fixture</w:t></w:r></w:p>"
            "<w:sectPr/></w:body></w:document>",
        )
    return output.getvalue()


def _multipart(name: str, media_type: str, data: bytes) -> tuple[bytes, str]:
    boundary = "jap-smoke-" + uuid4().hex
    body = bytearray()
    for field, value in (
        ("kind", "RESUME"),
        ("display_name", "Synthetic mail fixture"),
    ):
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n'
            f"\r\n{value}\r\n".encode()
        )
    body.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{name}"\r\nContent-Type: {media_type}\r\n\r\n'.encode()
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), "multipart/form-data; boundary=" + boundary


def probe(api_url: str) -> None:
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("Mail smoke requires an explicit IPv4 loopback API port")
    token = os.environ.get("JAP_API_TOKEN")
    environment = os.environ.get("JAP_ENVIRONMENT", "")
    configuration = json.loads(os.environ.get("JAP_COMMUNICATION_CONFIG_JSON", "null"))
    if (
        not token
        or not environment.startswith("package-smoke-")
        or configuration != {"providers": [], "oauth_clients": []}
    ):
        raise RuntimeError(
            "Mail smoke requires an isolated, explicitly disabled provider configuration"
        )
    opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(
        path: str,
        body: dict[str, Any] | bytes | None = None,
        *,
        expected: int = 200,
        content_type: str = "application/json",
    ) -> Any:
        payload = json.dumps(body).encode() if isinstance(body, dict) else body
        req = Request(
            api_url.rstrip("/") + "/api/v1" + path,
            data=payload,
            headers={"Content-Type": content_type, "X-Job-Apply-Pro-Token": token},
            method="GET" if body is None else "POST",
        )
        try:
            response = opener.open(req, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            data = response.read(1_048_577)
            if response.status != expected or len(data) > 1_048_576:
                raise RuntimeError(
                    "Packaged mail API returned an unexpected status or oversized body"
                )
        return json.loads(data)

    health = request("/health")
    if health.get("environment") != environment:
        raise RuntimeError("Mail smoke API is not the isolated test backend")
    integrations = request("/communications/integrations")
    if len(integrations) != 4 or any(
        item.get("status") != "NOT_CONFIGURED" or item.get("write_enabled")
        for item in integrations
    ):
        raise RuntimeError("Mail smoke refuses configured providers")
    candidate = request(
        "/candidates",
        {
            "display_name": "Synthetic packaged mail probe",
            "contact": {
                "full_name": "Synthetic Fixture",
                "email": "fixture@example.invalid",
            },
        },
        expected=201,
    )
    profile_id = str(UUID(candidate["id"]))
    workflow = request(
        "/workbench/mock-workflows",
        {
            "profile_id": profile_id,
            "employer": "Synthetic mail fixture",
            "title": "Packaged attachment validation",
        },
        expected=201,
    )
    workflow_id = workflow["workflow_id"]
    if not isinstance(workflow_id, str) or not workflow_id.startswith("mock-"):
        raise RuntimeError("Mail smoke returned an invalid synthetic workflow")
    UUID(workflow_id.removeprefix("mock-"))
    expected_attachments = []
    for name, media_type, data in (
        ("fixture.pdf", "application/pdf", _pdf()),
        (
            "fixture.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx(),
        ),
    ):
        body, content_type = _multipart(name, media_type, data)
        imported = request(
            f"/knowledge/profiles/{profile_id}/documents",
            body,
            content_type=content_type,
            expected=201,
        )
        expected_attachments.append(
            {
                "document_version_id": imported["version"]["id"],
                "document_id": imported["document"]["id"],
                "file_name": name,
                "media_type": media_type,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    for provider in ("GMAIL", "OUTLOOK"):
        record = request(
            "/communications/analyze",
            {
                "provider": provider,
                "provider_message_id": "synthetic-" + uuid4().hex,
                "provider_thread_id": "synthetic-thread",
                "sender": "recruiter@example.invalid",
                "recipients": ["fixture@example.invalid"],
                "subject": "Interview invitation",
                "body_text": "Please share your availability.",
                "received_at": datetime.now(UTC).isoformat(),
            },
            expected=201,
        )
        draft = request(
            "/communications/drafts",
            {
                "analysis_id": record["id"],
                "workflow_id": workflow_id,
                "provider": provider,
                "provider_thread_id": "synthetic-thread",
                "recipient": "recruiter@example.invalid",
                "subject": "Synthetic review only",
                "body_text": "No live mail may be sent.",
                "category": "INTERVIEW_REQUEST",
                "policy": "REVIEW_REQUIRED",
                "document_version_ids": [
                    item["document_version_id"] for item in expected_attachments
                ],
            },
            expected=201,
        )
        if (
            draft.get("attachment_manifest")
            != {
                "policy_version": "mail-attachments-v1",
                "profile_id": profile_id,
                "attachments": expected_attachments,
            }
            or "provider_binding_fingerprint" in draft
        ):
            raise RuntimeError(
                "Packaged mail review manifest or privacy boundary failed"
            )
        draft_id = str(UUID(draft["id"]))
        if request(f"/communications/drafts/{draft_id}") != draft:
            raise RuntimeError("Packaged encrypted mail draft did not round-trip")
        confirmation = {
            "fingerprint": draft["fingerprint"],
            "idempotency_key": "smoke-" + uuid4().hex,
            "confirmed_by": "synthetic-package-probe",
        }
        request(f"/communications/drafts/{draft_id}/send", confirmation, expected=503)
        audit = request(f"/communications/drafts/{draft_id}/send", confirmation)
        if (
            audit.get("status") != "FAILED"
            or audit.get("provider_resource_id") is not None
            or audit.get("error_code") != "ProviderNotConfiguredError"
        ):
            raise RuntimeError(
                "Packaged disabled mail send did not preserve its failed audit"
            )
        request(
            f"/communications/drafts/{draft_id}/send",
            {**confirmation, "idempotency_key": "smoke-" + uuid4().hex},
            expected=409,
        )
    audits = request("/communications/mutation-audits")
    if len(audits) != 2 or any(audit.get("status") != "FAILED" for audit in audits):
        raise RuntimeError(
            "Packaged mail send claims did not prevent duplicate attempts"
        )
    print(
        "Packaged PDF/DOCX manifests, encrypted draft round-trip and disabled-provider send admission passed."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    arguments = parser.parse_args()
    probe(arguments.api_url)
