import json

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from job_apply_pro.domain.communications import IntegrationProvider, MessageCategory


class CommunicationConfigurationError(ValueError):
    pass


class ProviderConnectionConfig(BaseModel):
    """Contains only non-secret metadata and an opaque OS credential reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: IntegrationProvider
    credential_reference: str = Field(min_length=1, max_length=200)
    account_hint: str | None = Field(default=None, max_length=200)
    granted_scopes: list[str] = Field(default_factory=list, max_length=100)
    read_enabled: bool = True
    write_enabled: bool = False


class CommunicationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: list[ProviderConnectionConfig] = Field(default_factory=list, max_length=4)
    automatic_categories: set[MessageCategory] = Field(default_factory=set)


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
