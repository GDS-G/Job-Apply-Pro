from datetime import datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


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
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"
    UPLOAD = "UPLOAD"
    WAIT_FOR = "WAIT_FOR"
    SCREENSHOT = "SCREENSHOT"


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


class BrowserTab(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    url: str
    title: str
    active: bool


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
    controls: list[dict[str, object]]
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
