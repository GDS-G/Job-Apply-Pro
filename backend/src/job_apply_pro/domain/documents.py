from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentKind(StrEnum):
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class Document(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    kind: DocumentKind
    display_name: str
    created_at: datetime


class DocumentVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    version: int = Field(ge=1)
    file_name: str
    media_type: str
    sha256: str = Field(min_length=64, max_length=64)
    storage_path: str
    created_at: datetime
