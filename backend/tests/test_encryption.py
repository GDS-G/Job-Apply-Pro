import base64

import pytest

from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import (
    EnvironmentKeyProvider,
    KeyConfigurationError,
    StaticKeyProvider,
)


def test_aes_gcm_round_trip_and_context_binding() -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"a" * 32))
    envelope = cipher.encrypt_json({"email": "person@example.com"}, context="candidate:1")

    assert "person@example.com" not in envelope
    assert cipher.decrypt_json(envelope, context="candidate:1") == {"email": "person@example.com"}
    with pytest.raises(DecryptionError):
        cipher.decrypt_json(envelope, context="candidate:2")


def test_tampering_is_rejected() -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"b" * 32))
    envelope = cipher.encrypt_json({"phone": "555-0100"}, context="candidate:2")
    replacement = "A" if envelope[-1] != "A" else "B"

    with pytest.raises(DecryptionError):
        cipher.decrypt_json(envelope[:-1] + replacement, context="candidate:2")


def test_environment_provider_requires_256_bit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAP_MASTER_KEY", base64.urlsafe_b64encode(b"short").decode())

    with pytest.raises(KeyConfigurationError):
        EnvironmentKeyProvider().load_key()
