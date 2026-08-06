import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import SecretStr, ValidationError

from job_apply_pro.domain.operations import (
    HelpTopic,
    LicenseEntitlement,
    LicenseState,
    LicenseStatus,
    SignedLicense,
)


class PaymentProvider(Protocol):
    def create_checkout(self, *, plan_id: str, device_public_key: str) -> str: ...


class PaymentNotConfiguredError(RuntimeError):
    pass


class DisabledPaymentProvider:
    def create_checkout(self, *, plan_id: str, device_public_key: str) -> str:
        del plan_id, device_public_key
        raise PaymentNotConfiguredError("Commercial payment processing is not configured")


class LicenseService:
    def __init__(
        self,
        public_key: SecretStr | None,
        signed_license_json: SecretStr | None,
        *,
        now: datetime | None = None,
    ) -> None:
        self._public_key = public_key
        self._signed_license_json = signed_license_json
        self._now = now or datetime.now(UTC)

    def state(self) -> LicenseState:
        if self._public_key is None and self._signed_license_json is None:
            return LicenseState(
                status=LicenseStatus.DEVELOPMENT,
                message="Personal development entitlement; payment is disabled",
            )
        if self._public_key is None or self._signed_license_json is None:
            return LicenseState(
                status=LicenseStatus.NOT_CONFIGURED,
                message="Signed license and verification key must be configured together",
            )
        try:
            signed = SignedLicense.model_validate_json(self._signed_license_json.get_secret_value())
            payload = base64.urlsafe_b64decode(signed.payload.encode("ascii"))
            signature = base64.urlsafe_b64decode(signed.signature.encode("ascii"))
            public_bytes = base64.urlsafe_b64decode(
                self._public_key.get_secret_value().encode("ascii")
            )
            Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, payload)
            entitlement = LicenseEntitlement.model_validate_json(payload)
        except (
            binascii.Error,
            UnicodeEncodeError,
            ValueError,
            ValidationError,
            InvalidSignature,
        ):
            return LicenseState(
                status=LicenseStatus.INVALID,
                message="License signature or payload is invalid",
            )
        if self._now <= entitlement.expires_at:
            return LicenseState(
                status=LicenseStatus.ACTIVE,
                message="Signed entitlement is active",
                entitlement=entitlement,
            )
        grace_end = entitlement.expires_at + timedelta(days=entitlement.offline_grace_days)
        if self._now <= grace_end:
            return LicenseState(
                status=LicenseStatus.GRACE_PERIOD,
                message="Entitlement is using its approved offline grace period",
                entitlement=entitlement,
            )
        return LicenseState(
            status=LicenseStatus.EXPIRED,
            message="Signed entitlement and offline grace period have expired",
            entitlement=entitlement,
        )


def help_topics() -> list[HelpTopic]:
    return [
        HelpTopic(
            id="safe-start",
            title="Start in supervised mode",
            summary=(
                "Create a profile, verify facts, and run fixtures before authorizing providers."
            ),
            steps=[
                "Create an encrypted candidate profile.",
                "Import and review document claims.",
                "Run the loopback Reference ATS workflow.",
                "Review every elevated action before confirmation.",
            ],
            context="workbench",
        ),
        HelpTopic(
            id="backup-restore",
            title="Back up and restore safely",
            summary="Create an encrypted archive, verify it, then stage restore files.",
            steps=[
                "Create a local backup from Operations.",
                "Verify the archive and every entry hash.",
                "Choose database, documents, or both for restore.",
                "Stop the backend before applying a verified database restore.",
            ],
            context="backup",
        ),
        HelpTopic(
            id="provider-authorization",
            title="Authorize an external provider",
            summary="Provider accounts stay disabled until credentials and consent exist.",
            steps=[
                "Register the provider client outside source control.",
                "Store tokens in the operating-system credential store.",
                "Grant only required read/write scopes.",
                "Validate fixture and supervised live behavior before enabling writes.",
            ],
            context="integrations",
        ),
        HelpTopic(
            id="recovery-access",
            title="Recovery is always available",
            summary="License status never blocks backup verification or restore staging.",
            steps=[
                "Open Operations and select a backup.",
                "Verify integrity before any restore action.",
                "Stage the selected categories.",
                "Apply only the exact reviewed restore fingerprint while offline.",
            ],
            context="licensing",
        ),
    ]
