"""Bounded unauthenticated GETs to one fixed public API; never application writes."""

import hashlib
import html
import json
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

from job_apply_pro.domain.job_discovery import (
    GreenhouseBoardRequest,
    GreenhouseJobList,
    GreenhouseJobReview,
    GreenhouseJobSummary,
    GreenhouseReviewRequest,
)
from job_apply_pro.domain.workflow import utc_now

API_ORIGIN = "https://boards-api.greenhouse.io"
NORMALIZER_VERSION = "greenhouse-text-v1"
MAX_LIST_BYTES = 2 * 1024 * 1024
MAX_DETAIL_BYTES = 512 * 1024
MAX_JOBS = 1000
MAX_OPERATION_SECONDS = 20
_HOSTED_ORIGINS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}


class GreenhouseDiscoveryError(ValueError):
    def __init__(self) -> None:
        super().__init__("The public board response was unavailable or outside supported limits")


class GreenhouseSourceUnavailableError(GreenhouseDiscoveryError):
    pass


def _text(value: object, limit: int, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or not _valid_unicode(value):
        raise GreenhouseDiscoveryError()
    result = " ".join(value.split())
    if not result:
        if optional:
            return None
        raise GreenhouseDiscoveryError()
    return result


def _valid_unicode(value: str) -> bool:
    return "\x00" not in value and not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise GreenhouseDiscoveryError()


def _updated_at(value: object) -> str | None:
    result = _text(value, 100, optional=True)
    if result is not None:
        try:
            parsed = datetime.fromisoformat(result)
            if parsed.tzinfo is None:
                raise ValueError("Timestamp requires an offset")
        except ValueError:
            raise GreenhouseDiscoveryError() from None
    return result


def _required_text(value: object, limit: int) -> str:
    result = _text(value, limit)
    if result is None:
        raise GreenhouseDiscoveryError()
    return result


def _identifier(value: object) -> str:
    if type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807:
        raise GreenhouseDiscoveryError()
    return str(value)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GreenhouseDiscoveryError()
        result[key] = value
    return result


def _invalid_json_constant(_value: str) -> object:
    raise GreenhouseDiscoveryError()


class _DescriptionParser(HTMLParser):
    _HIDDEN = frozenset({"script", "style", "template", "iframe", "object", "svg", "noscript"})
    _BLOCK = frozenset({"p", "div", "li", "ul", "ol", "br", "hr", "h1", "h2", "h3", "h4", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []
        self.size = 0

    def _append(self, value: str) -> None:
        self.size += len(value)
        if self.size > 100_000:
            raise GreenhouseDiscoveryError()
        self.parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN:
            self.hidden.append(tag)
            if len(self.hidden) > 100:
                raise GreenhouseDiscoveryError()
        if not self.hidden and tag in self._BLOCK:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden:
            self.hidden = self.hidden[: self.hidden.index(tag)]
        if not self.hidden and tag in self._BLOCK:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self._append(data)


def description_text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 250_000 or not _valid_unicode(value):
        raise GreenhouseDiscoveryError()
    # The API can entity-encode authored HTML. Decoding is deliberately bounded.
    for _ in range(2):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    parser = _DescriptionParser()
    parser.feed(value)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    result = "\n".join(line for line in lines if line)
    if not result or len(result) > 50_000:
        raise GreenhouseDiscoveryError()
    return result


def _posting_url(value: object, token: str, identifier: str) -> tuple[str, str | None]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2000
        or not _valid_unicode(value)
        or "\\" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise GreenhouseDiscoveryError()
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
        ):
            raise GreenhouseDiscoveryError()
        if parsed.hostname in _HOSTED_ORIGINS:
            if parsed.path != f"/{token}/jobs/{identifier}":
                raise GreenhouseDiscoveryError()
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=10)
            if set(query) - {"gh_src"} or any(len(values) != 1 for values in query.values()):
                raise GreenhouseDiscoveryError()
            return value, f"https://{parsed.hostname}/{token}/jobs/{identifier}"
        # Employer URLs are metadata only: no discovery fetch or navigation authority.
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        if "gh_jid" in query and query["gh_jid"] != [identifier]:
            raise GreenhouseDiscoveryError()
        return value, None
    except ValueError:
        raise GreenhouseDiscoveryError() from None


def _summary(value: object, token: str) -> GreenhouseJobSummary:
    if not isinstance(value, dict):
        raise GreenhouseDiscoveryError()
    identifier = _identifier(value.get("id"))
    if "internal_job_id" not in value:
        raise GreenhouseDiscoveryError()
    if value["internal_job_id"] is None:
        raise GreenhouseSourceUnavailableError()
    _identifier(value["internal_job_id"])
    location = value.get("location")
    if not isinstance(location, dict):
        raise GreenhouseDiscoveryError()
    _, source_url = _posting_url(value.get("absolute_url"), token, identifier)
    return GreenhouseJobSummary(
        posting_id=identifier,
        title=_required_text(value.get("title"), 200),
        location=_text(location.get("name"), 200, optional=True),
        source_url=source_url,
        navigation_supported=source_url is not None,
    )


class GreenhousePublicBoardClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _get(self, path: str, limit: int, deadline: float) -> dict[str, object]:
        _check_deadline(deadline)
        chunks: list[bytes] = []
        size = 0
        try:
            with httpx.Client(
                timeout=httpx.Timeout(5, pool=1),
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GreenhouseDiscoveryError()
                # Recheck after client/TLS setup and budget each transport phase.
                # This is not hard cancellation of a blocked OS/network operation.
                timeout = httpx.Timeout(min(5.0, remaining), pool=min(1.0, remaining))
                with client.stream(
                    "GET",
                    API_ORIGIN + path,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                    timeout=timeout,
                ) as response:
                    if response.status_code in {404, 410}:
                        raise GreenhouseSourceUnavailableError()
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        != "application/json"
                        or response.headers.get("content-encoding", "identity").lower()
                        != "identity"
                    ):
                        raise GreenhouseDiscoveryError()
                    # Do not aggregate small transport reads: a trickling response
                    # must expose every read to the total-deadline check.
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit or time.monotonic() > deadline:
                            raise GreenhouseDiscoveryError()
                        chunks.append(chunk)
            if time.monotonic() > deadline:
                raise GreenhouseDiscoveryError()
            payload = json.loads(
                b"".join(chunks),
                object_pairs_hook=_json_object,
                parse_constant=_invalid_json_constant,
            )
            if not isinstance(payload, dict):
                raise GreenhouseDiscoveryError()
            _check_deadline(deadline)
            return payload
        except GreenhouseDiscoveryError:
            raise
        except (httpx.HTTPError, ValueError, RecursionError):
            raise GreenhouseDiscoveryError() from None

    def list_jobs(self, command: GreenhouseBoardRequest) -> GreenhouseJobList:
        token = command.board_token
        deadline = time.monotonic() + MAX_OPERATION_SECONDS
        board = self._get(f"/v1/boards/{token}", 65_536, deadline)
        payload = self._get(f"/v1/boards/{token}/jobs", MAX_LIST_BYTES, deadline)
        values = payload.get("jobs")
        if not isinstance(values, list) or len(values) > MAX_JOBS:
            raise GreenhouseDiscoveryError()
        meta = payload.get("meta")
        if meta is not None and (
            not isinstance(meta, dict)
            or type(meta.get("total")) is not int
            or meta["total"] != len(values)
        ):
            raise GreenhouseDiscoveryError()
        jobs: dict[str, GreenhouseJobSummary] = {}
        raw: dict[str, object] = {}
        prospects: set[str] = set()
        for value in values:
            if not isinstance(value, dict):
                raise GreenhouseDiscoveryError()
            identifier = _identifier(value.get("id"))
            if identifier in raw:
                if value != raw[identifier]:
                    raise GreenhouseDiscoveryError()
                continue
            raw[identifier] = value
            if "internal_job_id" in value and value["internal_job_id"] is None:
                prospects.add(identifier)
                continue
            jobs[identifier] = _summary(value, token)
        result = GreenhouseJobList(
            board_token=token,
            board_name=_required_text(board.get("name"), 200),
            fetched_at=utc_now(),
            jobs=list(jobs.values()),
            excluded_prospect_count=len(prospects),
        )
        _check_deadline(deadline)
        return result

    def review_job(self, command: GreenhouseReviewRequest) -> GreenhouseJobReview:
        path = f"/v1/boards/{command.board_token}/jobs/{command.posting_id}"
        deadline = time.monotonic() + MAX_OPERATION_SECONDS
        payload = self._get(path, MAX_DETAIL_BYTES, deadline)
        summary = _summary(payload, command.board_token)
        if summary.posting_id != command.posting_id:
            raise GreenhouseDiscoveryError()
        reported, _ = _posting_url(
            payload.get("absolute_url"), command.board_token, command.posting_id
        )
        fields = {
            **summary.model_dump(),
            "board_token": command.board_token,
            "employer": _required_text(payload.get("company_name"), 200),
            "description": description_text(payload.get("content")),
            "api_url": API_ORIGIN + path,
            "reported_url": reported,
            "provider_updated_at": _updated_at(payload.get("updated_at")),
            "normalizer_version": NORMALIZER_VERSION,
            "qualification_status": "NOT_EVALUATED",
        }
        fingerprint = hashlib.sha256(
            json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        result = GreenhouseJobReview.model_validate(
            {**fields, "fetched_at": utc_now(), "review_fingerprint": fingerprint}
        )
        _check_deadline(deadline)
        return result
