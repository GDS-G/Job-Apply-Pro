import base64
import binascii
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from job_apply_pro.security.keys import KeyProvider


class DecryptionError(ValueError):
    pass


class SensitiveDataCipher:
    """Versioned AES-256-GCM envelopes bound to a record-specific context."""

    PREFIX = "jap:v1"
    NONCE_BYTES = 12

    def __init__(self, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider

    @property
    def key_id(self) -> str:
        return self._key_provider.key_id

    def encrypt_json(self, value: dict[str, object], *, context: str) -> str:
        plaintext = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        nonce = os.urandom(self.NONCE_BYTES)
        ciphertext = AESGCM(self._key_provider.load_key()).encrypt(
            nonce, plaintext, context.encode("utf-8")
        )
        encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return f"{self.PREFIX}:{self.key_id}:{encoded}"

    def decrypt_json(self, envelope: str, *, context: str) -> dict[str, object]:
        parts = envelope.split(":", 3)
        if len(parts) != 4 or ":".join(parts[:2]) != self.PREFIX:
            raise DecryptionError("Unsupported encrypted envelope")
        key_id, encoded = parts[2], parts[3]
        if key_id != self.key_id:
            raise DecryptionError("Encrypted envelope requires a different key")
        try:
            payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
            nonce, ciphertext = payload[: self.NONCE_BYTES], payload[self.NONCE_BYTES :]
            if len(nonce) != self.NONCE_BYTES or not ciphertext:
                raise ValueError
            plaintext = AESGCM(self._key_provider.load_key()).decrypt(
                nonce, ciphertext, context.encode("utf-8")
            )
            decoded: Any = json.loads(plaintext)
        except (
            UnicodeEncodeError,
            binascii.Error,
            ValueError,
            InvalidTag,
            json.JSONDecodeError,
        ) as error:
            raise DecryptionError("Encrypted data failed authentication") from error
        if not isinstance(decoded, dict):
            raise DecryptionError("Encrypted payload is not a JSON object")
        return decoded

    def validate_envelope(self, envelope: str, *, context: str) -> None:
        self.decrypt_json(envelope, context=context)
