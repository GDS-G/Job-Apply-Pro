from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import IntegrationProvider, OAuthTokenSet
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.models import OAuthAuthorizationSessionRow, OAuthCredentialRow


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True)
class OAuthAuthorizationSession:
    state_hash: str
    provider: IntegrationProvider
    client_id: str
    redirect_uri: str
    requested_scopes: list[str]
    code_verifier: str
    expires_at: datetime


class OAuthRepository:
    """Persists only encrypted token/verifier material and opaque public references."""

    def __init__(self, session: Session, cipher: SensitiveDataCipher) -> None:
        self._session = session
        self._cipher = cipher

    def save_authorization_session(self, value: OAuthAuthorizationSession) -> None:
        self._session.execute(
            delete(OAuthAuthorizationSessionRow).where(
                OAuthAuthorizationSessionRow.provider == value.provider.value
            )
        )
        self._session.add(
            OAuthAuthorizationSessionRow(
                state_hash=value.state_hash,
                provider=value.provider.value,
                client_id=value.client_id,
                redirect_uri=value.redirect_uri,
                requested_scopes_json=value.requested_scopes,
                encrypted_code_verifier=self._cipher.encrypt_json(
                    {"code_verifier": value.code_verifier},
                    context=f"oauth-session:{value.state_hash}:verifier",
                ),
                expires_at=value.expires_at,
                consumed_at=None,
            )
        )
        self._session.commit()

    def consume_authorization_session(
        self, state_hash: str, *, now: datetime
    ) -> OAuthAuthorizationSession | None:
        row = self._session.get(OAuthAuthorizationSessionRow, state_hash)
        if row is None or row.consumed_at is not None or _utc(row.expires_at) <= now:
            return None
        payload = self._cipher.decrypt_json(
            row.encrypted_code_verifier,
            context=f"oauth-session:{row.state_hash}:verifier",
        )
        row.consumed_at = now
        self._session.commit()
        return OAuthAuthorizationSession(
            state_hash=row.state_hash,
            provider=IntegrationProvider(row.provider),
            client_id=row.client_id,
            redirect_uri=row.redirect_uri,
            requested_scopes=[str(scope) for scope in row.requested_scopes_json],
            code_verifier=str(payload["code_verifier"]),
            expires_at=_utc(row.expires_at),
        )

    def save_tokens(
        self,
        provider: IntegrationProvider,
        credential_reference: str,
        tokens: OAuthTokenSet,
        *,
        now: datetime,
    ) -> None:
        existing = self._session.scalar(
            select(OAuthCredentialRow).where(OAuthCredentialRow.provider == provider.value)
        )
        if existing is not None and existing.credential_reference != credential_reference:
            self._session.delete(existing)
            self._session.flush()
            existing = None
        payload: dict[str, object] = {
            "access_token": tokens.access_token.get_secret_value(),
            "refresh_token": (
                tokens.refresh_token.get_secret_value()
                if tokens.refresh_token is not None
                else None
            ),
            "token_type": tokens.token_type,
            "expires_at": tokens.expires_at.isoformat(),
            "granted_scopes": tokens.granted_scopes,
            "account_hint": tokens.account_hint,
        }
        encrypted = self._cipher.encrypt_json(
            payload, context=f"oauth-credential:{credential_reference}:tokens"
        )
        if existing is None:
            existing = OAuthCredentialRow(
                credential_reference=credential_reference,
                provider=provider.value,
                encrypted_token_set=encrypted,
                granted_scopes_json=tokens.granted_scopes,
                account_hint=tokens.account_hint,
                expires_at=tokens.expires_at,
                updated_at=now,
            )
            self._session.add(existing)
        else:
            existing.encrypted_token_set = encrypted
            existing.granted_scopes_json = tokens.granted_scopes
            existing.account_hint = tokens.account_hint
            existing.expires_at = tokens.expires_at
            existing.updated_at = now
        self._session.commit()

    def load_tokens(self, provider: IntegrationProvider) -> tuple[str, OAuthTokenSet] | None:
        row = self._session.scalar(
            select(OAuthCredentialRow).where(OAuthCredentialRow.provider == provider.value)
        )
        if row is None:
            return None
        payload = self._cipher.decrypt_json(
            row.encrypted_token_set,
            context=f"oauth-credential:{row.credential_reference}:tokens",
        )
        return row.credential_reference, OAuthTokenSet.model_validate(payload)

    def delete_tokens(self, provider: IntegrationProvider) -> bool:
        row = self._session.scalar(
            select(OAuthCredentialRow).where(OAuthCredentialRow.provider == provider.value)
        )
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True
