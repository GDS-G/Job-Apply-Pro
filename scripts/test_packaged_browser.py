"""Exercise the packaged browser worker using isolated, loopback-only fixtures.

Requires an installed Playwright Chromium runtime, as provisioned by CI. This
probe does not import backend source, use personal profiles, or contact portals.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

_PAGE = b"""<!doctype html><html><head><title>Packaged Browser Fixture</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
</head><body data-page-type="QUESTIONNAIRE"><h1>Synthetic packaged browser fixture</h1>
<label for="answer">Synthetic answer</label><input id="answer" name="answer" required>
</body></html>"""


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/fixture" else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_PAGE)))
        self.end_headers()
        self.wfile.write(_PAGE)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


def _worker_error_category(value: object) -> str:
    """Classify expected failures without reflecting paths, page data, or secrets."""
    if not isinstance(value, dict) or not isinstance(value.get("message"), str):
        return "INVALID_WORKER_ERROR"
    message = value["message"]
    if "Executable doesn't exist" in message:
        return "PLAYWRIGHT_BROWSER_EXECUTABLE_MISSING"
    if "missing dependencies" in message.lower():
        return "BROWSER_SYSTEM_DEPENDENCIES_MISSING"
    if "DLL load failed" in message or "Cannot find module" in message:
        return "PACKAGED_RUNTIME_DEPENDENCY_MISSING"
    if "Target page, context or browser has been closed" in message:
        return "BROWSER_CLOSED_DURING_COMMAND"
    if "timeout" in message.lower() or "timed out" in message.lower():
        return "BROWSER_COMMAND_TIMEOUT"
    return "UNCLASSIFIED_WORKER_ERROR"


class _WorkerProbe:
    def __init__(self, executable: Path, root: Path) -> None:
        self._stderr = (root / "direct-worker.stderr.log").open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                [str(executable), "browser-worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
                cwd=root,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self._stderr.close()
            raise
        self._lines: Queue[str | None] = Queue()
        self._reader = Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def call(
        self, method: str, params: dict[str, object], *, timeout: int = 90
    ) -> dict[str, Any]:
        assert self.process.stdin is not None
        request_id = str(uuid4())
        self.process.stdin.write(
            json.dumps({"id": request_id, "method": method, "params": params})
        )
        self.process.stdin.write("\n")
        self.process.stdin.flush()
        try:
            line = self._lines.get(timeout=timeout)
        except Empty as error:
            raise RuntimeError(f"Packaged worker timed out during {method}") from error
        if line is None or len(line) > 1_048_576:
            raise RuntimeError(
                "Packaged worker exited or returned an oversized response"
            )
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise RuntimeError(
                "Packaged worker JSON-lines response did not match its request"
            )
        result = response.get("result")
        if "error" in response or not isinstance(result, dict):
            category = _worker_error_category(response.get("error"))
            raise RuntimeError(
                f"Packaged worker rejected {method} ({category}); "
                "only a sanitized failure category is reported"
            )
        return result

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self.call("shutdown", {}, timeout=10)
                except (OSError, RuntimeError, ValueError):
                    if self.process.stdin is not None:
                        self.process.stdin.close()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
            self._stderr.close()


def _artifact(value: object, root: Path) -> None:
    if not isinstance(value, str):
        raise TypeError("Packaged browser did not report an artifact path")
    path = Path(value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError(
            "Packaged browser artifact is missing or outside its isolated directory"
        )


def _observation(value: object, fixture_url: str, root: Path) -> int:
    if not isinstance(value, dict):
        raise TypeError("Packaged browser observation is missing")
    if (
        value.get("url") != fixture_url
        or value.get("title") != "Packaged Browser Fixture"
        or value.get("page_type") != "QUESTIONNAIRE"
        or "Synthetic packaged browser fixture" not in str(value.get("visible_text"))
        or not value.get("controls")
    ):
        raise RuntimeError(
            "Packaged browser did not observe the synthetic loopback fixture"
        )
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        raise RuntimeError("Packaged browser returned an invalid observation sequence")
    _artifact(value.get("screenshot_path"), root)
    return sequence


def _direct_worker(executable: Path, fixture_url: str, root: Path) -> None:
    worker = _WorkerProbe(executable, root)
    session_id = str(uuid4())
    try:
        created = worker.call(
            "start_session",
            {
                "session_id": session_id,
                "workflow_id": "synthetic-packaged-direct-workflow",
                "engine": "chromium",
                "profile_dir": str(root / "direct-profile"),
                "artifact_dir": str(root / "direct-artifacts"),
                "start_url": fixture_url,
                "current_url": fixture_url,
                "allowed_origins": [fixture_url.removesuffix("/fixture")],
                "headless": True,
            },
        )
        first_sequence = _observation(created, fixture_url, root)
        observed = worker.call("observe", {"session_id": session_id})
        if _observation(observed, fixture_url, root) <= first_sequence:
            raise RuntimeError(
                "Packaged worker did not advance its observation sequence"
            )
        stopped = worker.call("stop_session", {"session_id": session_id})
        _artifact(stopped.get("trace_path"), root)
        if worker.call("shutdown", {}, timeout=10) != {"stopped": True}:
            raise RuntimeError("Packaged worker did not acknowledge shutdown")
        if worker.process.wait(timeout=15) != 0:
            raise RuntimeError("Packaged worker did not exit cleanly after shutdown")
    finally:
        worker.close()


def _packaged_api(api_url: str, fixture_url: str, root: Path) -> None:
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("Packaged smoke API must use an explicit IPv4 loopback port")
    token = os.environ.get("JAP_API_TOKEN")
    if not token:
        raise RuntimeError("Packaged smoke requires an isolated API token")
    opener = build_opener(ProxyHandler({}), _NoRedirect())

    def post(path: str, body: dict[str, object] | None = None) -> dict[str, Any]:
        request = Request(
            api_url.rstrip("/") + "/api/v1" + path,
            data=json.dumps(body or {}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Job-Apply-Pro-Token": token,
            },
            method="POST",
        )
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise TypeError("Packaged API returned an invalid object")
        return result

    candidate = post(
        "/candidates",
        {
            "display_name": "Synthetic packaged browser probe",
            "contact": {
                "full_name": "Synthetic Fixture",
                "email": "fixture@example.invalid",
            },
        },
    )
    workflow = post(
        "/workbench/mock-workflows",
        {
            "profile_id": str(UUID(candidate["id"])),
            "employer": "Synthetic loopback fixture",
            "title": "Packaged runtime validation",
        },
    )
    created = post(
        "/browser/sessions",
        {
            "workflow_id": str(UUID(workflow["workflow_id"])),
            "start_url": fixture_url,
            "engine": "chromium",
            "profile_name": "packaged-api-" + uuid4().hex,
            "headless": True,
        },
    )
    session_id = str(UUID(created["id"]))
    try:
        if created.get("state") != "ACTIVE":
            raise RuntimeError("Packaged API browser session did not become active")
        sequence = _observation(created.get("observation"), fixture_url, root)
        observed = post(f"/browser/sessions/{session_id}/observe")
        if _observation(observed.get("observation"), fixture_url, root) <= sequence:
            raise RuntimeError("Packaged API browser observation did not advance")
    finally:
        stopped = post(f"/browser/sessions/{session_id}/stop")
        if stopped.get("state") != "STOPPED":
            raise RuntimeError("Packaged API browser session did not stop")
        _artifact(stopped.get("trace_path"), root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("--test-root", required=True, type=Path)
    parser.add_argument("--api-url", required=True)
    args = parser.parse_args()
    worker = args.worker.resolve(strict=True)
    root = args.test_root.resolve(strict=True)
    if not worker.is_file() or not root.is_dir():
        raise RuntimeError("Packaged worker and isolated smoke directory are required")
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    server_thread = Thread(target=fixture.serve_forever, daemon=True)
    server_thread.start()
    try:
        fixture_url = f"http://127.0.0.1:{fixture.server_port}/fixture"
        _direct_worker(worker, fixture_url, root)
        _packaged_api(args.api_url, fixture_url, root)
    finally:
        fixture.shutdown()
        fixture.server_close()
        server_thread.join(timeout=5)
    print(
        "Packaged worker JSON-lines lifecycle and packaged API browser lifecycle passed "
        "(loopback only)."
    )


if __name__ == "__main__":
    main()
