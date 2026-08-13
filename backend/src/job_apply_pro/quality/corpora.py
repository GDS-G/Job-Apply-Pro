from __future__ import annotations

import json
import re
from collections.abc import Callable
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_apply_pro.domain.ai import AgentRole, AgentRunRequest, EvaluationCase
from job_apply_pro.domain.knowledge import DocumentExtraction

MAX_CORPUS_BYTES = 1_000_000
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "password",
    "refresh_token",
    "routing_number",
    "social_security_number",
    "ssn",
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class CorpusValidationError(ValueError):
    pass


class CorpusClassification(StrEnum):
    SANITIZED_SYNTHETIC = "SANITIZED_SYNTHETIC"


class AIEvaluationCorpusCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    role: AgentRole
    input_data: dict[str, object]
    fixture_output: dict[str, object]
    required_keys: set[str] = Field(default_factory=set)
    expected_values: dict[str, object] = Field(default_factory=dict)
    required_json_pointers: set[str] = Field(default_factory=set, max_length=50)
    expected_json_pointer_values: dict[str, object] = Field(default_factory=dict)
    allowed_evidence_ids: set[str] = Field(default_factory=set, max_length=200)
    evidence_json_pointer: str = Field(default="/evidence_claim_ids", max_length=500)
    forbidden_output_terms: list[str] = Field(default_factory=list, max_length=50)
    repeat_count: int = Field(default=2, ge=2, le=5)

    def evaluation_case(self, corpus_version: str) -> EvaluationCase:
        return EvaluationCase(
            id=self.id,
            agent_request=AgentRunRequest(
                role=self.role,
                input_data=self.input_data,
                source_version=f"sanitized-ai-corpus/{corpus_version}",
            ),
            required_keys=self.required_keys,
            expected_values=self.expected_values,
            required_json_pointers=self.required_json_pointers,
            expected_json_pointer_values=self.expected_json_pointer_values,
            allowed_evidence_ids=self.allowed_evidence_ids,
            evidence_json_pointer=self.evidence_json_pointer,
            forbidden_output_terms=self.forbidden_output_terms,
            repeat_count=self.repeat_count,
        )


class AIEvaluationCorpus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    corpus_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    classification: CorpusClassification
    cases: list[AIEvaluationCorpusCase] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_case_identity(self) -> Self:
        identifiers = [case.id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("AI corpus case IDs must be unique")
        _validate_sanitized_payload(self.model_dump(mode="json"))
        return self

    def evaluation_cases(self) -> list[EvaluationCase]:
        return [case.evaluation_case(self.corpus_version) for case in self.cases]


class DocumentFixtureKind(StrEnum):
    PLAIN_TEXT = "PLAIN_TEXT"
    MARKDOWN = "MARKDOWN"
    RTF = "RTF"
    DOCX_SECTION_TABLE = "DOCX_SECTION_TABLE"
    DOCX_NESTED_FLOATING = "DOCX_NESTED_FLOATING"
    PDF_SINGLE_COLUMN = "PDF_SINGLE_COLUMN"
    PDF_TWO_COLUMN = "PDF_TWO_COLUMN"
    PDF_PARTIAL_BLANK = "PDF_PARTIAL_BLANK"


class DocumentIngestionCorpusCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    fixture_kind: DocumentFixtureKind
    file_name: str = Field(min_length=1, max_length=255)
    fixture_values: dict[str, object]
    expected_media_type: str = Field(min_length=1, max_length=200)
    expected_parser: str = Field(min_length=1, max_length=100)
    expected_block_text: list[str] = Field(min_length=1, max_length=100)
    expected_block_kinds: list[str] = Field(min_length=1, max_length=100)
    expected_warnings: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_expected_blocks(self) -> Self:
        if len(self.expected_block_text) != len(self.expected_block_kinds):
            raise ValueError("Expected document block text and kind counts must match")
        return self


class DocumentIngestionCorpus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    corpus_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    classification: CorpusClassification
    cases: list[DocumentIngestionCorpusCase] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_case_identity(self) -> Self:
        identifiers = [case.id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Document corpus case IDs must be unique")
        _validate_sanitized_payload(self.model_dump(mode="json"))
        return self


class DocumentCorpusCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    failures: list[str]


class DocumentCorpusReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    corpus_version: str
    total: int
    passed: int
    failed: int
    cases: list[DocumentCorpusCaseResult]


DocumentFixtureFactory = Callable[[DocumentIngestionCorpusCase], bytes]
DocumentExtractor = Callable[[str, bytes], tuple[str, DocumentExtraction]]


def run_document_ingestion_corpus(
    corpus: DocumentIngestionCorpus,
    fixture_factory: DocumentFixtureFactory,
    extractor: DocumentExtractor,
) -> DocumentCorpusReport:
    results: list[DocumentCorpusCaseResult] = []
    for case in corpus.cases:
        failures: list[str] = []
        try:
            media_type, extraction = extractor(case.file_name, fixture_factory(case))
        except Exception as error:  # corpus reports the normalized failure without hiding its type
            failures.append(f"extraction failed: {type(error).__name__}")
        else:
            if media_type != case.expected_media_type:
                failures.append("unexpected media type")
            if extraction.parser != case.expected_parser:
                failures.append("unexpected parser")
            if [block.text for block in extraction.blocks] != case.expected_block_text:
                failures.append("unexpected block text")
            if [block.kind for block in extraction.blocks] != case.expected_block_kinds:
                failures.append("unexpected block kinds")
            if extraction.warnings != case.expected_warnings:
                failures.append("unexpected warnings")
        results.append(
            DocumentCorpusCaseResult(case_id=case.id, passed=not failures, failures=failures)
        )
    passed = sum(result.passed for result in results)
    return DocumentCorpusReport(
        corpus_version=corpus.corpus_version,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        cases=results,
    )


def parse_ai_evaluation_corpus(data: bytes) -> AIEvaluationCorpus:
    return _parse_corpus(data, AIEvaluationCorpus)


def parse_document_ingestion_corpus(data: bytes) -> DocumentIngestionCorpus:
    return _parse_corpus(data, DocumentIngestionCorpus)


def _parse_corpus[CorpusModel: BaseModel](data: bytes, model: type[CorpusModel]) -> CorpusModel:
    if not data or len(data) > MAX_CORPUS_BYTES:
        raise CorpusValidationError("Corpus JSON is empty or exceeds the size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
        return model.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CorpusValidationError("Corpus JSON failed validation") from error


def _validate_sanitized_payload(value: object, *, key: str | None = None) -> None:
    if key and key.casefold() in SENSITIVE_KEYS:
        raise ValueError("Sanitized corpora cannot contain sensitive fields")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _validate_sanitized_payload(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            _validate_sanitized_payload(child)
    elif isinstance(value, str) and EMAIL_PATTERN.search(value):
        raise ValueError("Sanitized corpora cannot contain email addresses")
