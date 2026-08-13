import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class BrowserEngine(StrEnum):
    CHROMIUM = "chromium"
    CHROME = "chrome"
    EDGE = "msedge"


class BrowserSessionState(StrEnum):
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    USER_TAKEOVER = "USER_TAKEOVER"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class LocatorStrategy(StrEnum):
    ROLE = "ROLE"
    LABEL = "LABEL"
    TEXT = "TEXT"
    TEST_ID = "TEST_ID"
    CSS = "CSS"
    XPATH = "XPATH"
    ACCESSIBILITY = "ACCESSIBILITY"
    COORDINATE = "COORDINATE"


class BrowserActionKind(StrEnum):
    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    FILL = "FILL"
    SELECT = "SELECT"
    SELECT_LABEL = "SELECT_LABEL"
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"
    UPLOAD = "UPLOAD"
    WAIT_FOR = "WAIT_FOR"
    SCREENSHOT = "SCREENSHOT"


class BrowserControlKind(StrEnum):
    TEXT = "TEXT"
    TEXT_AREA = "TEXT_AREA"
    EMAIL = "EMAIL"
    TELEPHONE = "TELEPHONE"
    NUMBER = "NUMBER"
    DATE = "DATE"
    SELECT = "SELECT"
    RADIO_GROUP = "RADIO_GROUP"
    CHECKBOX = "CHECKBOX"
    FILE_UPLOAD = "FILE_UPLOAD"
    SIGNATURE = "SIGNATURE"
    DISCLOSURE = "DISCLOSURE"
    BUTTON = "BUTTON"
    LINK = "LINK"
    CUSTOM = "CUSTOM"


class BrowserPermission(StrEnum):
    READ = "READ"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


class ConfirmationState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    CONFIRMED = "CONFIRMED"


class VerificationKind(StrEnum):
    NONE = "NONE"
    URL_CONTAINS = "URL_CONTAINS"
    TITLE_CONTAINS = "TITLE_CONTAINS"
    TEXT_VISIBLE = "TEXT_VISIBLE"
    LOCATOR_VISIBLE = "LOCATOR_VISIBLE"
    VALUE_EQUALS = "VALUE_EQUALS"
    SELECTED_LABEL_EQUALS = "SELECTED_LABEL_EQUALS"
    CHECKED_EQUALS = "CHECKED_EQUALS"


class SemanticLocator(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: LocatorStrategy
    value: str = Field(min_length=1, max_length=500)
    name: str | None = Field(default=None, max_length=300)
    exact: bool = True


class BrowserCoordinates(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0)
    y: float = Field(ge=0)


class BrowserVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: VerificationKind = VerificationKind.NONE
    value: str | None = Field(default=None, max_length=500)
    locator: SemanticLocator | None = None


class BrowserRetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=3)
    backoff_ms: int = Field(default=0, ge=0, le=5_000)
    allow_after_worker_restart: bool = False


class BrowserAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: BrowserActionKind
    locator: SemanticLocator | None = None
    coordinates: BrowserCoordinates | None = None
    url: AnyHttpUrl | None = None
    value: str | None = Field(default=None, max_length=10_000)
    file_path: str | None = Field(default=None, max_length=2_000)
    preconditions: list[BrowserVerification] = Field(default_factory=list, max_length=10)
    intended_result: str = Field(min_length=1, max_length=500)
    timeout_ms: int = Field(default=10_000, ge=250, le=60_000)
    verification: BrowserVerification = Field(default_factory=BrowserVerification)
    retry: BrowserRetryPolicy = Field(default_factory=BrowserRetryPolicy)
    permission: BrowserPermission = BrowserPermission.STANDARD
    confirmation: ConfirmationState = ConfirmationState.NOT_REQUIRED
    sensitive_value: bool = False


class BrowserTab(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    url: str
    title: str
    active: bool


class BrowserControlOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str = Field(max_length=500)
    label: str = Field(max_length=300)
    locator: SemanticLocator | None = None


class BrowserObservedControl(BaseModel):
    """Privacy-bounded, deterministic description of one observed page control."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0, le=999)
    control_key: str = Field(min_length=1, max_length=200)
    kind: BrowserControlKind
    tag: str = Field(max_length=40)
    input_type: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=80)
    element_id: str = Field(default="", max_length=300)
    field_name: str = Field(default="", max_length=300)
    group_label: str = Field(default="", max_length=300)
    label: str = Field(default="", max_length=300)
    label_source: str = Field(default="NONE", max_length=40)
    text: str = Field(default="", max_length=200)
    href: str = Field(default="", max_length=2_000)
    canonical_field: str = Field(default="", max_length=160)
    accept: str = Field(default="", max_length=500)
    checked: bool = False
    required: bool = False
    native_required: bool = False
    accessible_required: bool = False
    disabled: bool = False
    native_disabled: bool = False
    accessible_disabled: bool = False
    visible: bool = False
    will_validate: bool = False
    constraint_satisfied: bool = False
    accessible_invalid: bool = False
    legal_attestation: bool = False
    character_limit: int | None = Field(default=None, ge=1, le=20_000)
    minimum_number: float | None = None
    maximum_number: float | None = None
    earliest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    latest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    options: list[BrowserControlOption] = Field(default_factory=list, max_length=100)
    locator: SemanticLocator | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_worker_control(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        item = dict(value)
        tag = str(item.get("tag", "")).casefold()[:40]
        input_type = str(item.get("input_type", item.get("type", ""))).casefold()[:40]
        role = str(item.get("role", ""))[:80]
        label = str(item.get("label", "")).strip()[:300]
        text = str(item.get("text", "")).strip()[:200]
        field_name = str(item.get("field_name", item.get("fieldName", "")))[:300]
        element_id = str(item.get("element_id", item.get("id", "")))[:300]
        group_label = str(item.get("group_label", item.get("groupLabel", "")))[:300]
        label_source = str(item.get("label_source", item.get("labelSource", "NONE")))[:40]
        canonical_field = str(item.get("canonical_field", item.get("canonicalField", "")))[:160]
        raw_options = item.get("options", [])
        options = []
        if isinstance(raw_options, list):
            for option in raw_options[:100]:
                if isinstance(option, BaseModel):
                    option = option.model_dump(mode="json")
                if isinstance(option, dict):
                    option_value = str(option.get("value", ""))[:500]
                    option_label = str(option.get("label", option_value))[:300]
                    option_locator = option.get("locator")
                else:
                    option_value = option_label = str(option)[:300]
                    option_locator = None
                options.append(
                    {
                        "value": option_value,
                        "label": option_label,
                        "locator": option_locator,
                    }
                )
        if tag == "textarea":
            kind = BrowserControlKind.TEXT_AREA
        elif tag == "select":
            kind = BrowserControlKind.SELECT
        elif tag == "button" or role == "button" or input_type in {"button", "submit"}:
            kind = BrowserControlKind.BUTTON
        elif tag == "a" or role == "link":
            kind = BrowserControlKind.LINK
        elif input_type == "email":
            kind = BrowserControlKind.EMAIL
        elif input_type == "tel":
            kind = BrowserControlKind.TELEPHONE
        elif input_type == "number":
            kind = BrowserControlKind.NUMBER
        elif input_type == "date":
            kind = BrowserControlKind.DATE
        elif input_type == "radio":
            kind = BrowserControlKind.RADIO_GROUP
        elif input_type == "checkbox":
            kind = BrowserControlKind.CHECKBOX
        elif input_type == "file":
            kind = BrowserControlKind.FILE_UPLOAD
        elif tag == "input" and input_type not in {"hidden", "password"}:
            kind = BrowserControlKind.TEXT
        else:
            kind = BrowserControlKind.CUSTOM
        semantic_name = (group_label if input_type == "radio" and group_label else label) or str(
            item.get("name", "")
        ).strip()[:300]
        locator: dict[str, object] | None = None
        role_by_kind = {
            BrowserControlKind.TEXT: "textbox",
            BrowserControlKind.TEXT_AREA: "textbox",
            BrowserControlKind.EMAIL: "textbox",
            BrowserControlKind.TELEPHONE: "textbox",
            BrowserControlKind.NUMBER: "spinbutton",
            BrowserControlKind.DATE: "textbox",
            BrowserControlKind.SELECT: "combobox",
            BrowserControlKind.CHECKBOX: "checkbox",
        }
        if semantic_name and label_source == "ARIA_LABELLEDBY" and kind in role_by_kind:
            locator = {
                "strategy": LocatorStrategy.ROLE,
                "value": role_by_kind[kind],
                "name": semantic_name,
                "exact": True,
            }
        elif semantic_name:
            locator = {
                "strategy": LocatorStrategy.LABEL,
                "value": semantic_name,
                "exact": True,
            }
        elif kind in {BrowserControlKind.BUTTON, BrowserControlKind.LINK} and text:
            locator = {
                "strategy": LocatorStrategy.ROLE,
                "value": "button" if kind is BrowserControlKind.BUTTON else "link",
                "name": text,
                "exact": True,
            }
        index = int(item.get("index", 0))
        key_payload = {
            "id": element_id,
            "name": field_name,
            "label": semantic_name,
            "tag": tag,
            "type": input_type,
            "group": group_label,
            "index": 0 if input_type == "radio" and field_name else index,
        }
        control_key = (
            str(item.get("control_key", "")).strip()
            or hashlib.sha256(
                json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:32]
        )
        legal_text = " ".join((label, group_label, text)).casefold()
        legal_attestation = bool(item.get("legal_attestation")) or bool(
            re.search(
                r"\b(?:certif(?:y|ication)|attest|signature|consent|agree|terms)\b", legal_text
            )
        )
        if "signature" in legal_text:
            kind = BrowserControlKind.SIGNATURE
        elif re.search(r"\b(?:disclosure|consent|terms)\b", legal_text):
            kind = BrowserControlKind.DISCLOSURE

        def optional_scalar(*names: str) -> object | None:
            for name in names:
                candidate = item.get(name)
                if candidate not in {None, ""}:
                    return candidate
            return None

        href = str(item.get("href", ""))[:2_000]
        if href:
            parsed_href = urlsplit(href)
            href = urlunsplit((parsed_href.scheme, parsed_href.netloc, parsed_href.path, "", ""))[
                :2_000
            ]
        native_required = bool(
            item.get("native_required", item.get("nativeRequired", item.get("required")))
        )
        accessible_required = bool(item.get("accessible_required", item.get("accessibleRequired")))
        native_disabled = bool(
            item.get("native_disabled", item.get("nativeDisabled", item.get("disabled")))
        )
        accessible_disabled = bool(item.get("accessible_disabled", item.get("accessibleDisabled")))
        return {
            "index": index,
            "control_key": control_key,
            "kind": kind,
            "tag": tag,
            "input_type": input_type,
            "role": role,
            "element_id": element_id,
            "field_name": field_name,
            "group_label": group_label,
            "label": label,
            "label_source": label_source,
            "text": text,
            "href": href,
            "canonical_field": canonical_field,
            "accept": str(item.get("accept", ""))[:500],
            "checked": bool(item.get("checked")),
            "required": bool(item.get("required")) or native_required or accessible_required,
            "native_required": native_required,
            "accessible_required": accessible_required,
            "disabled": bool(item.get("disabled")) or native_disabled or accessible_disabled,
            "native_disabled": native_disabled,
            "accessible_disabled": accessible_disabled,
            "visible": bool(item.get("visible")),
            "will_validate": bool(item.get("will_validate", item.get("willValidate"))),
            "constraint_satisfied": bool(
                item.get("constraint_satisfied", item.get("constraintSatisfied"))
            ),
            "accessible_invalid": bool(
                item.get("accessible_invalid", item.get("accessibleInvalid"))
            ),
            "legal_attestation": legal_attestation,
            "character_limit": optional_scalar("character_limit", "maxLength"),
            "minimum_number": optional_scalar("minimum_number", "min"),
            "maximum_number": optional_scalar("maximum_number", "max"),
            "earliest_date": optional_scalar("earliest_date", "minDate"),
            "latest_date": optional_scalar("latest_date", "maxDate"),
            "options": options,
            "locator": locator,
        }


class BrowserObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=1)
    url: str
    title: str
    origin: str
    page_type: str
    page_fingerprint: str
    tabs: list[BrowserTab]
    accessibility_snapshot: str
    visible_text: str
    controls: list[BrowserObservedControl]
    validation_errors: list[str]
    modals: list[str]
    console_errors: list[str]
    network_failures: list[str]
    upload_status: list[str]
    download_status: list[str]
    screenshot_path: str
    trace_path: str | None = None
    previous_action: str | None = None
    observed_at: datetime


class BrowserSessionCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(min_length=1, max_length=100)
    start_url: AnyHttpUrl
    engine: BrowserEngine = BrowserEngine.CHROMIUM
    profile_name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    headless: bool | None = None
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)


class BrowserSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    engine: BrowserEngine
    profile_name: str
    state: BrowserSessionState
    current_url: str
    allowed_origins: list[str]
    observation: BrowserObservation | None
    action_count: int = Field(ge=0)
    trace_path: str | None = None
    created_at: datetime
    updated_at: datetime


class BrowserSessionRecord(BrowserSessionSnapshot):
    model_config = ConfigDict(frozen=True)

    user_data_dir: str
    artifact_dir: str
    headless: bool


class BrowserActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    session_id: str
    sequence: int = Field(ge=1)
    action: BrowserAction
    verified: bool
    attempts: int = Field(ge=1, le=3)
    observation: BrowserObservation
    error: str | None = None
    created_at: datetime
