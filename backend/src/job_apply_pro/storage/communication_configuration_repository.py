from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from job_apply_pro.integrations.configuration import (
    CommunicationConfiguration,
    CommunicationConfigurationError,
)
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.storage.models import CommunicationConfigurationRow

ACTIVE_CONFIGURATION_ID = "active"
ENCRYPTION_CONTEXT = "communication-configuration:active"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class CommunicationConfigurationRepository:
    """Stores the active provider registration configuration as authenticated ciphertext."""

    def __init__(self, session: Session, cipher: SensitiveDataCipher) -> None:
        self._session = session
        self._cipher = cipher

    def load(self) -> tuple[CommunicationConfiguration, datetime] | None:
        row = self._session.get(CommunicationConfigurationRow, ACTIVE_CONFIGURATION_ID)
        if row is None:
            return None
        try:
            payload = self._cipher.decrypt_json(
                row.encrypted_configuration,
                context=ENCRYPTION_CONTEXT,
            )
            return CommunicationConfiguration.model_validate(payload), _utc(row.updated_at)
        except (DecryptionError, ValidationError) as error:
            raise CommunicationConfigurationError(
                "Encrypted communication configuration could not be authenticated or validated"
            ) from error

    def save(
        self,
        configuration: CommunicationConfiguration,
        *,
        now: datetime | None = None,
    ) -> datetime:
        updated_at = now or datetime.now(UTC)
        encrypted = self._cipher.encrypt_json(
            configuration.model_dump(mode="json"),
            context=ENCRYPTION_CONTEXT,
        )
        row = self._session.get(CommunicationConfigurationRow, ACTIVE_CONFIGURATION_ID)
        if row is None:
            row = CommunicationConfigurationRow(
                id=ACTIVE_CONFIGURATION_ID,
                encrypted_configuration=encrypted,
                updated_at=updated_at,
            )
            self._session.add(row)
        else:
            row.encrypted_configuration = encrypted
            row.updated_at = updated_at
        self._session.commit()
        return updated_at

    def delete(self) -> bool:
        row = self._session.get(CommunicationConfigurationRow, ACTIVE_CONFIGURATION_ID)
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True
