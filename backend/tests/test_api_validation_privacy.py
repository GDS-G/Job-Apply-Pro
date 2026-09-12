from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from job_apply_pro.api.routes.ai import get_ai_gateway
from job_apply_pro.config import get_settings
from job_apply_pro.main import create_app


@pytest.fixture
def validation_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-validation-token")
    get_settings.cache_clear()
    application = create_app()
    # No database, key lookup, journal, or provider can run for these inputs.
    application.dependency_overrides[get_ai_gateway] = object
    client = TestClient(
        application, headers={"X-Job-Apply-Pro-Token": "synthetic-validation-token"}
    )
    try:
        yield client
    finally:
        client.close()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "part",
    [
        {
            "kind": "media",
            "mime_type": "image/png",
            "data": base64.b64encode(b"\x89PNG\r\n\x1a\nprivate-fixture").decode(),
        },
        {
            "kind": "media",
            "mime_type": "image/jpeg",
            "data": base64.b64encode(b"\xff\xd8\xff\xfeprivate-fixture").decode(),
        },
        {"kind": "media", "mime_type": "image/png", "data": "not base64 private-fixture!"},
        {"kind": "text", "value": "private-fixture", "unexpected-private-field": "private-fixture"},
    ],
)
def test_validation_does_not_echo_media_or_input(
    validation_client: TestClient, part: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    response = validation_client.post(
        "/api/v1/ai/invoke",
        json={
            "task_type": "ANSWER",
            "prompt_id": "answer",
            "input_data": {},
            "input_parts": [part],
            "media_upload_consent": True,
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request validation failed; check required fields and supported values"
    }
    assert "private-fixture" not in caplog.text


def test_malformed_json_is_not_reflected(validation_client: TestClient) -> None:
    response = validation_client.post(
        "/api/v1/ai/invoke",
        content=b'{"private-fixture":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "private-fixture" not in response.text


def test_authentication_precedes_validation(validation_client: TestClient) -> None:
    response = validation_client.post(
        "/api/v1/ai/invoke",
        json={"private-fixture": True},
        headers={"X-Job-Apply-Pro-Token": "wrong"},
    )
    assert response.status_code == 401
