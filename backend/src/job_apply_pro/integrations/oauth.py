from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from pydantic import SecretStr

from job_apply_pro.domain.communications import (
    IntegrationProvider,
    IntegrationStatus,
    OAuthAuthorizationRequest,
    OAuthAuthorizationState,
    OAuthCallbackResult,
    OAuthTokenSet,
)
from job_apply_pro.integrations.configuration import OAuthClientConfig
from job_apply_pro.storage.oauth_repository import OAuthAuthorizationSession, OAuthRepository


class OAuthConfigurationError(RuntimeError):
    pass


class OAuthAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthProviderDefinition:
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str | None
    profile_endpoint: str
    permitted_scopes: frozenset[str]


_GOOGLE_AUTHORIZATION = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
_GOOGLE_PROFILE = "https://openidconnect.googleapis.com/v1/userinfo"
_MICROSOFT_AUTHORIZATION = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
_MICROSOFT_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
_MICROSOFT_PROFILE = "https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName"

OAUTH_PROVIDERS: dict[IntegrationProvider, OAuthProviderDefinition] = {
    IntegrationProvider.GMAIL: OAuthProviderDefinition(
        authorization_endpoint=_GOOGLE_AUTHORIZATION,
        token_endpoint=_GOOGLE_TOKEN,
        revocation_endpoint=_GOOGLE_REVOKE,
        profile_endpoint=_GOOGLE_PROFILE,
        permitted_scopes=frozenset(
            {
                "openid",
                "email",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            }
        ),
    ),
    IntegrationProvider.GOOGLE_CALENDAR: OAuthProviderDefinition(
        authorization_endpoint=_GOOGLE_AUTHORIZATION,
        token_endpoint=_GOOGLE_TOKEN,
        revocation_endpoint=_GOOGLE_REVOKE,
        profile_endpoint=_GOOGLE_PROFILE,
        permitted_scopes=frozenset(
            {
                "openid",
                "email",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            }
        ),
    ),
    IntegrationProvider.OUTLOOK: OAuthProviderDefinition(
        authorization_endpoint=_MICROSOFT_AUTHORIZATION,
        token_endpoint=_MICROSOFT_TOKEN,
        revocation_endpoint=None,
        profile_endpoint=_MICROSOFT_PROFILE,
        permitted_scopes=frozenset(
            {"openid", "email", "offline_access", "User.Read", "Mail.Read", "Mail.Send"}
        ),
    ),
    IntegrationProvider.OUTLOOK_CALENDAR: OAuthProviderDefinition(
        authorization_endpoint=_MICROSOFT_AUTHORIZATION,
        token_endpoint=_MICROSOFT_TOKEN,
        revocation_endpoint=None,
        profile_endpoint=_MICROSOFT_PROFILE,
        permitted_scopes=frozenset(
            {
                "openid",
                "email",
                "offline_access",
                "User.Read",
                "Calendars.Read",
                "Calendars.ReadWrite",
            }
        ),
    ),
}


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("ascii")).hexdigest()


def _scopes(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        return sorted(set(value.split()))
    return sorted(set(fallback))


class AccessTokenProvider(Protocol):
    def access_token(self, provider: IntegrationProvider) -> str: ...


class OAuthConnectionService:
    """Authorization Code + PKCE lifecycle with encrypted, one-time state persistence."""

    def __init__(
        self,
        repository: OAuthRepository,
        clients: dict[IntegrationProvider, OAuthClientConfig],
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clients = clients
        self._client = client or httpx.Client(timeout=30, follow_redirects=False)
        self._now = now or (lambda: datetime.now(UTC))

    def start(self, provider: IntegrationProvider) -> OAuthAuthorizationRequest:
        config = self._config(provider)
        definition = OAUTH_PROVIDERS[provider]
        requested = set(config.requested_scopes)
        if not requested <= definition.permitted_scopes:
            unknown = ", ".join(sorted(requested - definition.permitted_scopes))
            raise OAuthConfigurationError(f"Unapproved OAuth scopes requested: {unknown}")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        expires_at = self._now() + timedelta(minutes=10)
        self._repository.save_authorization_session(
            OAuthAuthorizationSession(
                state_hash=_state_hash(state),
                provider=provider,
                client_id=config.client_id,
                redirect_uri=config.redirect_uri,
                requested_scopes=sorted(requested),
                code_verifier=verifier,
                expires_at=expires_at,
            )
        )
        query = urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "response_mode": "query",
                "scope": " ".join(sorted(requested)),
                "state": state,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        return OAuthAuthorizationRequest(
            provider=provider,
            authorization_url=f"{definition.authorization_endpoint}?{query}",
            state=state,
            expires_at=expires_at,
        )

    def complete(self, *, code: str, state: str) -> OAuthCallbackResult:
        session = self._repository.consume_authorization_session(
            _state_hash(state), now=self._now()
        )
        if session is None:
            raise OAuthAuthorizationError("OAuth state is invalid, expired, or already consumed")
        definition = OAUTH_PROVIDERS[session.provider]
        response = self._client.post(
            definition.token_endpoint,
            data={
                "client_id": session.client_id,
                "code": code,
                "code_verifier": session.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": session.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        payload = self._token_payload(response)
        account_hint = self._account_hint(definition, str(payload["access_token"]))
        tokens = self._tokens(payload, session.requested_scopes, account_hint=account_hint)
        reference = f"oauth:{session.provider.value.casefold()}:{uuid4()}"
        self._repository.save_tokens(session.provider, reference, tokens, now=self._now())
        return OAuthCallbackResult(
            provider=session.provider,
            status=IntegrationStatus.CONNECTED,
            account_hint=account_hint,
            granted_scopes=tokens.granted_scopes,
        )

    def state(self, provider: IntegrationProvider) -> OAuthAuthorizationState:
        stored = self._repository.load_tokens(provider)
        if stored is None:
            return OAuthAuthorizationState(
                provider=provider,
                status=(
                    IntegrationStatus.AUTHORIZATION_REQUIRED
                    if provider in self._clients
                    else IntegrationStatus.NOT_CONFIGURED
                ),
            )
        reference, tokens = stored
        if tokens.expires_at <= self._now() and tokens.refresh_token is None:
            return OAuthAuthorizationState(
                provider=provider,
                status=IntegrationStatus.AUTHORIZATION_REQUIRED,
                credential_reference=reference,
                granted_scopes=tokens.granted_scopes,
                expires_at=tokens.expires_at,
                account_hint=tokens.account_hint,
            )
        return OAuthAuthorizationState(
            provider=provider,
            status=IntegrationStatus.CONNECTED,
            credential_reference=reference,
            granted_scopes=tokens.granted_scopes,
            expires_at=tokens.expires_at,
            account_hint=tokens.account_hint,
        )

    def revoke(self, provider: IntegrationProvider) -> OAuthAuthorizationState:
        stored = self._repository.load_tokens(provider)
        if stored is not None:
            _, tokens = stored
            endpoint = OAUTH_PROVIDERS[provider].revocation_endpoint
            if endpoint is not None:
                token = (
                    tokens.refresh_token.get_secret_value()
                    if tokens.refresh_token is not None
                    else tokens.access_token.get_secret_value()
                )
                response = self._client.post(endpoint, data={"token": token})
                if response.status_code >= 400:
                    raise OAuthAuthorizationError("Provider token revocation failed")
            self._repository.delete_tokens(provider)
        return self.state(provider)

    def access_token(self, provider: IntegrationProvider) -> str:
        stored = self._repository.load_tokens(provider)
        if stored is None:
            raise OAuthAuthorizationError(f"{provider.value} authorization is required")
        reference, tokens = stored
        if tokens.expires_at > self._now() + timedelta(seconds=60):
            return tokens.access_token.get_secret_value()
        if tokens.refresh_token is None:
            raise OAuthAuthorizationError(f"{provider.value} authorization has expired")
        config = self._config(provider)
        response = self._client.post(
            OAUTH_PROVIDERS[provider].token_endpoint,
            data={
                "client_id": config.client_id,
                "refresh_token": tokens.refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
                "scope": " ".join(tokens.granted_scopes),
            },
            headers={"Accept": "application/json"},
        )
        payload = self._token_payload(response)
        if "refresh_token" not in payload:
            payload["refresh_token"] = tokens.refresh_token.get_secret_value()
        refreshed = self._tokens(payload, tokens.granted_scopes, account_hint=tokens.account_hint)
        self._repository.save_tokens(provider, reference, refreshed, now=self._now())
        return refreshed.access_token.get_secret_value()

    def _config(self, provider: IntegrationProvider) -> OAuthClientConfig:
        config = self._clients.get(provider)
        if config is None:
            raise OAuthConfigurationError(f"{provider.value} OAuth client is not configured")
        return config

    @staticmethod
    def _token_payload(response: httpx.Response) -> dict[str, object]:
        if response.status_code >= 400:
            raise OAuthAuthorizationError("OAuth token exchange or refresh failed")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise OAuthAuthorizationError("OAuth provider returned an invalid token response")
        return payload

    def _tokens(
        self,
        payload: dict[str, object],
        fallback_scopes: list[str],
        *,
        account_hint: str | None,
    ) -> OAuthTokenSet:
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(expires_in, int | float) or expires_in <= 0:
            raise OAuthAuthorizationError("OAuth provider returned an invalid expiry")
        refresh = payload.get("refresh_token")
        return OAuthTokenSet(
            access_token=SecretStr(str(payload["access_token"])),
            refresh_token=(
                SecretStr(str(refresh)) if isinstance(refresh, str) and refresh else None
            ),
            token_type=str(payload.get("token_type", "Bearer")),
            expires_at=self._now() + timedelta(seconds=float(expires_in)),
            granted_scopes=_scopes(payload.get("scope"), fallback_scopes),
            account_hint=account_hint,
        )

    def _account_hint(self, definition: OAuthProviderDefinition, access_token: str) -> str | None:
        response = self._client.get(
            definition.profile_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        for key in ("email", "mail", "userPrincipalName"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None
