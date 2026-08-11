import json
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from job_apply_pro.domain.communications import IntegrationProvider, MessageCategory


class CommunicationConfigurationError(ValueError):
    pass


class ProviderConnectionConfig(BaseModel):
    """Contains only non-secret metadata and an opaque OS credential reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: IntegrationProvider
    credential_reference: str | None = Field(default=None, min_length=1, max_length=200)
    account_hint: str | None = Field(default=None, max_length=200)
    granted_scopes: list[str] = Field(default_factory=list, max_length=100)
    read_enabled: bool = True
    write_enabled: bool = False


class OAuthClientConfig(BaseModel):
    """Public desktop OAuth registration metadata; never contains account passwords or tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: IntegrationProvider
    client_id: str = Field(min_length=1, max_length=500)
    redirect_uri: str = Field(
        default="http://127.0.0.1:8765/api/v1/communications/oauth/callback",
        min_length=1,
        max_length=2_000,
    )
    requested_scopes: list[str] = Field(min_length=1, max_length=100)

    @field_validator("redirect_uri")
    @classmethod
    def require_loopback_callback(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path != "/api/v1/communications/oauth/callback"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OAuth redirect must use the exact loopback callback path")
        return value

    @field_validator("requested_scopes")
    @classmethod
    def normalize_scopes(cls, value: list[str]) -> list[str]:
        normalized = sorted({scope.strip() for scope in value if scope.strip()})
        if not normalized or any(len(scope) > 500 for scope in normalized):
            raise ValueError("OAuth scopes must be non-empty and at most 500 characters")
        return normalized


class CommunicationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: list[ProviderConnectionConfig] = Field(default_factory=list, max_length=4)
    oauth_clients: list[OAuthClientConfig] = Field(default_factory=list, max_length=4)
    automatic_categories: set[MessageCategory] = Field(default_factory=set)

    @model_validator(mode="after")
    def unique_provider_entries(self) -> "CommunicationConfiguration":
        for values in (self.providers, self.oauth_clients):
            providers = [item.provider for item in values]
            if len(providers) != len(set(providers)):
                raise ValueError(
                    "Communication providers must be unique in each configuration list"
                )
        return self


def build_communication_configuration(
    config_json: SecretStr | None,
) -> CommunicationConfiguration:
    if config_json is None:
        return CommunicationConfiguration()
    try:
        payload = json.loads(config_json.get_secret_value())
        return CommunicationConfiguration.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise CommunicationConfigurationError(
            "JAP_COMMUNICATION_CONFIG_JSON must contain credential references, not tokens"
        ) from error
