from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserObservation,
    BrowserObservedControl,
    BrowserTab,
    BrowserVerification,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def _bounded(values: list[str], *, count: int = 50, length: int = 500) -> list[str]:
    return [value[:length] for value in values[-count:]]


@dataclass
class WorkerSession:
    session_id: str
    workflow_id: str
    engine: str
    profile_dir: Path
    artifact_dir: Path
    start_url: str
    current_url: str
    allowed_origins: set[str]
    headless: bool
    context: BrowserContext
    active_page: Page
    observation_sequence: int = 0
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[str] = field(default_factory=list)
    modals: list[str] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    previous_action: str | None = None
    trace_path: str | None = None


class BrowserWorker:
    def __init__(self) -> None:
        self._playwright: Playwright = sync_playwright().start()
        self._sessions: dict[str, WorkerSession] = {}

    def close(self) -> None:
        for session_id in list(self._sessions):
            self.stop_session(session_id)
        self._playwright.stop()

    def _launch(self, data: dict[str, Any]) -> WorkerSession:
        engine = str(data["engine"])
        browser_type = self._playwright.chromium
        channel = None if engine == "chromium" else engine
        profile_dir = Path(str(data["profile_dir"])).resolve()
        artifact_dir = Path(str(data["artifact_dir"])).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        context = browser_type.launch_persistent_context(
            str(profile_dir),
            channel=channel,
            headless=bool(data["headless"]),
            accept_downloads=True,
            downloads_path=str(artifact_dir / "downloads"),
            viewport={"width": 1440, "height": 960},
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.pages[0] if context.pages else context.new_page()
        session = WorkerSession(
            session_id=str(data["session_id"]),
            workflow_id=str(data["workflow_id"]),
            engine=engine,
            profile_dir=profile_dir,
            artifact_dir=artifact_dir,
            start_url=str(data["start_url"]),
            current_url=str(data["current_url"]),
            allowed_origins=set(data["allowed_origins"]),
            headless=bool(data["headless"]),
            context=context,
            active_page=page,
        )
        self._sessions[session.session_id] = session
        for existing_page in context.pages:
            self._attach_page(session, existing_page)
        context.on("page", lambda new_page: self._attach_page(session, new_page))
        self._navigate(session, session.current_url)
        return session

    def start_session(self, data: dict[str, Any]) -> dict[str, object]:
        session_id = str(data["session_id"])
        if session_id in self._sessions:
            raise ValueError(f"Browser session {session_id} is already running")
        return self._observe(self._launch(data)).model_dump(mode="json")

    def observe(self, session_id: str) -> dict[str, object]:
        return self._observe(self._require(session_id)).model_dump(mode="json")

    def execute(self, session_id: str, action_data: dict[str, Any]) -> dict[str, object]:
        session = self._require(session_id)
        action = BrowserAction.model_validate(action_data)
        attempts = 0
        error: Exception | None = None
        for attempts in range(1, action.retry.max_attempts + 1):
            try:
                for precondition in action.preconditions:
                    if not self._verify(session, precondition):
                        raise RuntimeError(f"Precondition {precondition.kind} failed")
                self._perform(session, action)
                self._assert_allowed(session, session.active_page.url)
                verified = self._verify(session, action.verification)
                if not verified:
                    raise RuntimeError(f"Verification {action.verification.kind} failed")
                observation = self._observe(session)
                return {
                    "verified": True,
                    "attempts": attempts,
                    "observation": observation.model_dump(mode="json"),
                    "error": None,
                }
            except Exception as caught:  # worker boundary normalizes Playwright errors
                error = caught
                if attempts < action.retry.max_attempts:
                    if action.retry.allow_after_worker_restart:
                        session = self._restart_session(session)
                    if action.retry.backoff_ms:
                        time.sleep(action.retry.backoff_ms / 1000)
        observation = self._observe(session)
        return {
            "verified": False,
            "attempts": attempts,
            "observation": observation.model_dump(mode="json"),
            "error": str(error)[:1_000] if error else "Browser action failed",
        }

    def restart_session(self, session_id: str) -> dict[str, object]:
        return self._observe(self._restart_session(self._require(session_id))).model_dump(
            mode="json"
        )

    def _restart_session(self, session: WorkerSession) -> WorkerSession:
        session_id = session.session_id
        data = {
            "session_id": session.session_id,
            "workflow_id": session.workflow_id,
            "engine": session.engine,
            "profile_dir": str(session.profile_dir),
            "artifact_dir": str(session.artifact_dir),
            "start_url": session.start_url,
            "current_url": session.active_page.url or session.current_url,
            "allowed_origins": sorted(session.allowed_origins),
            "headless": session.headless,
        }
        self._close_context(session)
        del self._sessions[session_id]
        return self._launch(data)

    def stop_session(self, session_id: str) -> dict[str, object]:
        session = self._require(session_id)
        trace_path = self._close_context(session)
        del self._sessions[session_id]
        return {"trace_path": trace_path}

    def _close_context(self, session: WorkerSession) -> str:
        trace_path = session.artifact_dir / f"trace-{int(time.time() * 1000)}.zip"
        try:
            session.context.tracing.stop(path=str(trace_path))
            session.trace_path = str(trace_path)
        finally:
            session.context.close()
        return str(trace_path)

    def _require(self, session_id: str) -> WorkerSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise LookupError(f"Browser session {session_id} is not running")
        return session

    def _attach_page(self, session: WorkerSession, page: Page) -> None:
        page.on(
            "console",
            lambda message: (
                session.console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on(
            "requestfailed",
            lambda request: session.network_failures.append(
                f"{request.method} {request.url}: {request.failure or 'failed'}"
            ),
        )
        page.on(
            "response",
            lambda response: (
                session.network_failures.append(f"HTTP {response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )
        page.on("dialog", lambda dialog: self._handle_dialog(session, dialog))
        page.on("download", lambda download: session.downloads.append(download.suggested_filename))

    def _handle_dialog(self, session: WorkerSession, dialog: Any) -> None:
        session.modals.append(f"{dialog.type}: {dialog.message}")
        dialog.dismiss()

    def _assert_allowed(self, session: WorkerSession, url: str) -> None:
        origin = _origin(url)
        if not origin or origin not in session.allowed_origins:
            raise PermissionError(f"Navigation to origin {origin or 'unknown'} is not allowed")

    def _navigate(self, session: WorkerSession, url: str) -> None:
        self._assert_allowed(session, url)
        session.active_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._assert_allowed(session, session.active_page.url)
        session.current_url = session.active_page.url

    def _locator(self, page: Page, spec: SemanticLocator) -> Locator:
        if spec.strategy is LocatorStrategy.ROLE:
            return page.get_by_role(cast(Any, spec.value), name=spec.name, exact=spec.exact)
        if spec.strategy is LocatorStrategy.LABEL:
            return page.get_by_label(spec.value, exact=spec.exact)
        if spec.strategy is LocatorStrategy.TEXT:
            return page.get_by_text(spec.value, exact=spec.exact)
        if spec.strategy is LocatorStrategy.TEST_ID:
            return page.get_by_test_id(spec.value)
        if spec.strategy is LocatorStrategy.XPATH:
            return page.locator(f"xpath={spec.value}")
        if spec.strategy is LocatorStrategy.ACCESSIBILITY:
            return page.locator(f"[aria-label={json.dumps(spec.value)}]")
        if spec.strategy is LocatorStrategy.CSS:
            return page.locator(spec.value)
        raise ValueError(f"Locator strategy {spec.strategy} requires coordinates")

    def _perform(self, session: WorkerSession, action: BrowserAction) -> None:
        page = session.active_page
        timeout = action.timeout_ms
        if action.kind is BrowserActionKind.NAVIGATE:
            if action.url is None:
                raise ValueError("NAVIGATE requires url")
            self._navigate(session, str(action.url))
        elif action.kind is BrowserActionKind.SCREENSHOT:
            pass
        elif action.coordinates is not None:
            if action.kind is not BrowserActionKind.CLICK:
                raise ValueError("Coordinates are supported only for CLICK")
            page.mouse.click(action.coordinates.x, action.coordinates.y)
        else:
            if action.locator is None:
                raise ValueError(f"{action.kind} requires a semantic locator")
            locator = self._locator(page, action.locator)
            if action.kind is BrowserActionKind.CLICK:
                locator.click(timeout=timeout)
                if (
                    action.verification.kind is VerificationKind.URL_CONTAINS
                    and action.verification.value
                ):
                    expected = action.verification.value
                    page.wait_for_url(lambda url: expected in url, timeout=timeout)
            elif action.kind is BrowserActionKind.FILL:
                locator.fill(action.value or "", timeout=timeout)
            elif action.kind is BrowserActionKind.SELECT:
                if action.value is None:
                    raise ValueError("SELECT requires value")
                locator.select_option(action.value, timeout=timeout)
            elif action.kind is BrowserActionKind.SELECT_LABEL:
                if action.value is None:
                    raise ValueError("SELECT_LABEL requires a visible label")
                locator.select_option(label=action.value, timeout=timeout)
            elif action.kind is BrowserActionKind.CHECK:
                locator.check(timeout=timeout)
            elif action.kind is BrowserActionKind.UNCHECK:
                locator.uncheck(timeout=timeout)
            elif action.kind is BrowserActionKind.UPLOAD:
                if action.file_path is None:
                    raise ValueError("UPLOAD requires file_path")
                locator.set_input_files(action.file_path, timeout=timeout)
                session.uploads.append(Path(action.file_path).name)
            elif action.kind is BrowserActionKind.WAIT_FOR:
                locator.wait_for(state="visible", timeout=timeout)
            else:
                raise ValueError(f"Unsupported browser action {action.kind}")
        session.previous_action = action.kind.value
        session.current_url = page.url

    def _verify(self, session: WorkerSession, rule: BrowserVerification) -> bool:
        page = session.active_page
        if rule.kind is VerificationKind.NONE:
            return True
        if rule.kind is VerificationKind.URL_CONTAINS:
            return bool(rule.value and rule.value in page.url)
        if rule.kind is VerificationKind.TITLE_CONTAINS:
            return bool(rule.value and rule.value in page.title())
        if rule.kind is VerificationKind.TEXT_VISIBLE:
            return bool(rule.value and page.get_by_text(rule.value).first.is_visible())
        if rule.locator is None:
            return False
        locator = self._locator(page, rule.locator).first
        if rule.kind is VerificationKind.LOCATOR_VISIBLE:
            return locator.is_visible()
        if rule.kind is VerificationKind.VALUE_EQUALS:
            return rule.value is not None and locator.input_value() == rule.value
        if rule.kind is VerificationKind.SELECTED_LABEL_EQUALS:
            selected_label = locator.evaluate(
                "el => el.selectedOptions?.[0]?.textContent?.trim() || ''"
            )
            return rule.value is not None and selected_label == rule.value
        if rule.kind is VerificationKind.CHECKED_EQUALS:
            return locator.is_checked() is (rule.value != "false")
        return False

    def _observe(self, session: WorkerSession) -> BrowserObservation:
        page = session.active_page
        if page.is_closed():
            open_pages = [
                candidate for candidate in session.context.pages if not candidate.is_closed()
            ]
            if not open_pages:
                page = session.context.new_page()
                self._attach_page(session, page)
            else:
                page = open_pages[-1]
            session.active_page = page
        session.observation_sequence += 1
        pages = [candidate for candidate in session.context.pages if not candidate.is_closed()]
        tabs = [
            BrowserTab(
                index=index,
                url=candidate.url,
                title=candidate.title(),
                active=candidate is page,
            )
            for index, candidate in enumerate(pages)
        ]
        headings = page.locator("h1,h2,h3").all_inner_texts()
        controls_raw: list[dict[str, object]] = page.locator(
            "input:not([type='hidden']):not([type='password']),select,textarea,button,a,[role]"
        ).evaluate_all(
            """els => {
              const isVisible = el => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' &&
                  rect.width > 0 && rect.height > 0;
              };
              const visibleEls = els.filter(isVisible).slice(0, 100);
              return visibleEls.map((el, index) => {
              const id = el.getAttribute('id') || '';
              const explicitLabel = id
                ? document.querySelector(`label[for="${CSS.escape(id)}"]`)
                : null;
              const wrappingLabel = el.closest('label');
              const fieldset = el.closest('fieldset');
              const legend = fieldset?.querySelector(':scope > legend');
              return {
                index,
                id,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || '',
                name: el.getAttribute('aria-label') || el.getAttribute('name') || '',
                fieldName: el.getAttribute('name') || '',
                groupLabel: (legend?.textContent || '').trim().slice(0, 300),
                label: (
                  el.getAttribute('aria-label') ||
                  explicitLabel?.innerText ||
                  wrappingLabel?.innerText ||
                  ''
                ).trim().slice(0, 300),
                text: (el.innerText || '').trim().slice(0, 200),
                href: el.getAttribute('href') || '',
                canonicalField: el.getAttribute('data-canonical-field') || '',
                accept: el.getAttribute('accept') || '',
                checked: 'checked' in el ? Boolean(el.checked) : false,
                maxLength: 'maxLength' in el && el.maxLength > 0 ? el.maxLength : null,
                min: el.getAttribute('min') || null,
                max: el.getAttribute('max') || null,
                minDate: el.getAttribute('type') === 'date' ? el.getAttribute('min') : null,
                maxDate: el.getAttribute('type') === 'date' ? el.getAttribute('max') : null,
                options: el.tagName.toLowerCase() === 'select'
                  ? Array.from(el.options).slice(0, 100).map(option => ({
                      value: option.value,
                      label: option.textContent?.trim().slice(0, 300) || option.value
                    }))
                  : el.getAttribute('type') === 'radio' && el.getAttribute('name')
                  ? visibleEls.filter(candidate =>
                      candidate.getAttribute('type') === 'radio' &&
                      candidate.getAttribute('name') === el.getAttribute('name')
                    ).slice(0, 100).map(candidate => {
                      const candidateId = candidate.getAttribute('id') || '';
                      const candidateLabel = candidateId
                        ? document.querySelector(`label[for="${CSS.escape(candidateId)}"]`)
                        : candidate.closest('label');
                      return {
                        value: 'value' in candidate ? String(candidate.value).slice(0, 500) : '',
                        label: (candidateLabel?.textContent || '').trim().slice(0, 300),
                        locator: (candidateLabel?.textContent || '').trim()
                          ? {
                              strategy: 'LABEL',
                              value: (candidateLabel?.textContent || '').trim().slice(0, 300),
                              exact: true
                            }
                          : null
                      };
                    })
                  : [],
                required: el.hasAttribute('required') ||
                  (el.getAttribute('aria-required') || '').toLowerCase() === 'true',
                nativeRequired: el.hasAttribute('required'),
                accessibleRequired:
                  (el.getAttribute('aria-required') || '').toLowerCase() === 'true',
                disabled: el.hasAttribute('disabled'),
                visible: true,
                willValidate: 'willValidate' in el ? Boolean(el.willValidate) : false,
                constraintSatisfied: 'willValidate' in el && el.willValidate && el.validity
                  ? Boolean(el.validity.valid) : false
              };
            }).filter((item, index, items) =>
              item.type !== 'radio' ||
              items.findIndex(candidate =>
                candidate.type === 'radio' &&
                candidate.fieldName === item.fieldName
              ) === index
            );
            }"""
        )
        form_signatures = page.locator("form").evaluate_all(
            """els => els.map(el => Array.from(el.elements)
              .filter(control => {
                const type = control.getAttribute('type') || '';
                const style = window.getComputedStyle(control);
                const rect = control.getBoundingClientRect();
                return type !== 'hidden' && type !== 'password' &&
                  style.visibility !== 'hidden' && style.display !== 'none' &&
                  rect.width > 0 && rect.height > 0;
              })
              .map(control => control.name || control.id || control.type))"""
        )
        fingerprint_source = json.dumps(
            {
                "origin": _origin(page.url),
                "path": urlsplit(page.url).path,
                "title": page.title(),
                "headings": headings,
                "forms": form_signatures,
                "controls": [
                    [item.get("tag"), item.get("type"), item.get("role"), item.get("name")]
                    for item in controls_raw
                ],
            },
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()[:32]
        screenshot_path = (
            session.artifact_dir / f"observation-{session.observation_sequence:04d}.png"
        )
        page.screenshot(path=str(screenshot_path), full_page=True)
        try:
            accessibility = page.locator("body").aria_snapshot(timeout=5_000)
        except Exception:
            accessibility = ""
        try:
            visible_text = page.locator("body").inner_text(timeout=5_000)
        except Exception:
            visible_text = ""
        try:
            validation_errors = page.locator(
                "[aria-invalid='true'],[role='alert'],.error,.validation-error"
            ).all_inner_texts()
        except Exception:
            validation_errors = []
        page_type = page.locator("body").get_attribute("data-page-type") or "UNKNOWN"
        session.current_url = page.url
        return BrowserObservation(
            sequence=session.observation_sequence,
            url=page.url,
            title=page.title(),
            origin=_origin(page.url),
            page_type=page_type[:100],
            page_fingerprint=fingerprint,
            tabs=tabs,
            accessibility_snapshot=accessibility[:20_000],
            visible_text=visible_text[:12_000],
            controls=[BrowserObservedControl.model_validate(value) for value in controls_raw],
            validation_errors=_bounded(validation_errors),
            modals=_bounded(session.modals),
            console_errors=_bounded(session.console_errors),
            network_failures=_bounded(session.network_failures),
            upload_status=_bounded(session.uploads),
            download_status=_bounded(session.downloads),
            screenshot_path=str(screenshot_path),
            trace_path=session.trace_path,
            previous_action=session.previous_action,
            observed_at=datetime.now(UTC),
        )


def _response(request_id: object, *, result: object = None, error: Exception | None = None) -> str:
    payload: dict[str, object] = {"id": request_id}
    if error is None:
        payload["result"] = result
    else:
        payload["error"] = {"type": type(error).__name__, "message": str(error)[:2_000]}
    return json.dumps(payload, separators=(",", ":"), default=str)


def main() -> None:
    worker = BrowserWorker()
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            request: dict[str, Any] = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            try:
                if method == "start_session":
                    result = worker.start_session(params)
                elif method == "observe":
                    result = worker.observe(str(params["session_id"]))
                elif method == "execute":
                    result = worker.execute(str(params["session_id"]), params["action"])
                elif method == "restart_session":
                    result = worker.restart_session(str(params["session_id"]))
                elif method == "stop_session":
                    result = worker.stop_session(str(params["session_id"]))
                elif method == "shutdown":
                    print(_response(request_id, result={"stopped": True}), flush=True)
                    return
                else:
                    raise ValueError(f"Unknown worker method {method}")
                print(_response(request_id, result=result), flush=True)
            except Exception as error:
                print(_response(request_id, error=error), flush=True)
    finally:
        worker.close()


if __name__ == "__main__":
    main()
