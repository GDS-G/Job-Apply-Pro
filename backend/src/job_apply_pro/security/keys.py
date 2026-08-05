import base64
import binascii
import os
from collections.abc import Callable
from typing import Protocol


class KeyConfigurationError(RuntimeError):
    pass


class KeyProvider(Protocol):
    @property
    def key_id(self) -> str: ...

    def load_key(self) -> bytes: ...


class EnvironmentKeyProvider:
    """Loads a 256-bit key at use time so it is never retained in settings dumps."""

    def __init__(self, variable: str = "JAP_MASTER_KEY", key_id: str = "local-v1") -> None:
        self._variable = variable
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def load_key(self) -> bytes:
        encoded = os.getenv(self._variable)
        if encoded is None:
            raise KeyConfigurationError(
                f"{self._variable} must contain a base64-encoded 32-byte key"
            )
        try:
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except (UnicodeEncodeError, binascii.Error, ValueError) as error:
            raise KeyConfigurationError(f"{self._variable} is not valid base64") from error
        if len(key) != 32:
            raise KeyConfigurationError(f"{self._variable} must decode to exactly 32 bytes")
        return key


class StaticKeyProvider:
    """Explicit provider for tests and platform keychain adapters."""

    def __init__(self, key: bytes, key_id: str = "test-v1") -> None:
        if len(key) != 32:
            raise KeyConfigurationError("AES-256 keys must be exactly 32 bytes")
        self._key_loader: Callable[[], bytes] = lambda: key
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def load_key(self) -> bytes:
        return self._key_loader()
