import json
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.config import get_settings
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.models import CommunicationConfigurationRow


def _configuration() -> dict[str, object]:
    return {
        "oauth_clients": [
            {
                "provider": "GMAIL",
                "client_id": "public-desktop-client-id",
                "requested_scopes": [
                    "openid",
                    "email",
                    "https://www.googleapis.com/auth/gmail.readonly",
                ],
            }
        ]
    }


def _client(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("JAP_API_TOKEN", "configuration-api-token")
    monkeypatch.delenv("JAP_COMMUNICATION_CONFIG_JSON", raising=False)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_cipher] = lambda: SensitiveDataCipher(StaticKeyProvider(b"c" * 32))
    return TestClient(app)


def test_configuration_import_is_validated_encrypted_and_clearable(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(session, monkeypatch)
    headers = {"X-Job-Apply-Pro-Token": "configuration-api-token"}
    payload = {"configuration_json": json.dumps(_configuration())}
    try:
        assert client.get("/api/v1/communications/configuration", headers=headers).json() == {
            "source": "NOT_CONFIGURED",
            "providers": [],
            "automatic_categories": [],
            "updated_at": None,
        }

        preview = client.post(
            "/api/v1/communications/configuration/validate",
            headers=headers,
            json=payload,
        )
        assert preview.status_code == 200
        assert preview.json()["source"] == "IMPORT_PREVIEW"
        assert preview.json()["providers"] == [
            {
                "provider": "GMAIL",
                "oauth_configured": True,
                "requested_scopes": [
                    "email",
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "openid",
                ],
                "read_enabled": True,
                "write_enabled": False,
            }
        ]
        assert "client_id" not in preview.text

        imported = client.post(
            "/api/v1/communications/configuration/import",
            headers=headers,
            json=payload,
        )
        assert imported.status_code == 200
        assert imported.json()["source"] == "ENCRYPTED_DATABASE"
        assert imported.json()["updated_at"] is not None
        row = session.scalar(select(CommunicationConfigurationRow))
        assert row is not None
        assert row.encrypted_configuration.startswith("jap:v1:test-v1:")
        assert "public-desktop-client-id" not in row.encrypted_configuration

        health = client.get("/api/v1/communications/integrations", headers=headers)
        assert health.status_code == 200
        gmail = next(item for item in health.json() if item["provider"] == "GMAIL")
        assert gmail["status"] == "AUTHORIZATION_REQUIRED"

        cleared = client.delete("/api/v1/communications/configuration", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["source"] == "NOT_CONFIGURED"
        assert session.scalar(select(CommunicationConfigurationRow)) is None
    finally:
        client.close()
        get_settings.cache_clear()


def test_configuration_import_rejects_secrets_and_environment_override(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(session, monkeypatch)
    headers = {"X-Job-Apply-Pro-Token": "configuration-api-token"}
    secret_configuration = _configuration()
    oauth_clients = cast(list[dict[str, object]], secret_configuration["oauth_clients"])
    oauth_clients[0]["client_secret"] = "must-not-be-stored"
    try:
        rejected = client.post(
            "/api/v1/communications/configuration/import",
            headers=headers,
            json={"configuration_json": json.dumps(secret_configuration)},
        )
        assert rejected.status_code == 422
        assert "must-not-be-stored" not in rejected.text
        assert session.scalar(select(CommunicationConfigurationRow)) is None

        oauth_clients[0].pop("client_secret")
        oauth_clients[0]["requested_scopes"] = ["https://example.test/unapproved-secret-scope"]
        unapproved = client.post(
            "/api/v1/communications/configuration/validate",
            headers=headers,
            json={"configuration_json": json.dumps(secret_configuration)},
        )
        assert unapproved.status_code == 422
        assert "unapproved-secret-scope" not in unapproved.text
    finally:
        client.close()
        get_settings.cache_clear()

    monkeypatch.setenv("JAP_COMMUNICATION_CONFIG_JSON", json.dumps(_configuration()))
    get_settings.cache_clear()
    environment_client = TestClient(create_app())
    try:
        status = environment_client.get("/api/v1/communications/configuration", headers=headers)
        assert status.status_code == 200
        assert status.json()["source"] == "ENVIRONMENT"
        assert (
            environment_client.post(
                "/api/v1/communications/configuration/import",
                headers=headers,
                json={"configuration_json": json.dumps(_configuration())},
            ).status_code
            == 409
        )
        assert (
            environment_client.delete(
                "/api/v1/communications/configuration", headers=headers
            ).status_code
            == 409
        )
    finally:
        environment_client.close()
        get_settings.cache_clear()
