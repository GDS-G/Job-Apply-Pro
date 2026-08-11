from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from uuid import uuid4


class BrowserWorkerError(RuntimeError):
    pass


class BrowserWorkerUnavailableError(BrowserWorkerError):
    pass


class BrowserWorkerClient:
    """JSON-lines RPC client for the isolated Playwright worker process."""

    def __init__(self, *, timeout_seconds: float = 75) -> None:
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._responses: dict[str, Queue[dict[str, Any]]] = {}
        self._responses_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        source_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        current_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{source_root}{os.pathsep}{current_python_path}"
            if current_python_path
            else str(source_root)
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [sys.executable, "-m", "job_apply_pro.browser.worker_process"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=environment,
            cwd=str(source_root),
            creationflags=creation_flags,
        )
        self._reader = threading.Thread(target=self._read_responses, daemon=True)
        self._reader.start()

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                self.call("shutdown", {}, timeout_seconds=10)
            except BrowserWorkerError:
                process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._process = None

    def call(
        self,
        method: str,
        params: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        with self._call_lock:
            self.start()
            process = self._process
            if process is None or process.stdin is None or process.poll() is not None:
                raise BrowserWorkerUnavailableError("Browser worker process is not available")
            request_id = str(uuid4())
            response_queue: Queue[dict[str, Any]] = Queue(maxsize=1)
            with self._responses_lock:
                self._responses[request_id] = response_queue
            try:
                payload = json.dumps(
                    {"id": request_id, "method": method, "params": params},
                    separators=(",", ":"),
                )
                process.stdin.write(payload + "\n")
                process.stdin.flush()
                try:
                    response = response_queue.get(timeout=timeout_seconds or self._timeout_seconds)
                except Empty as error:
                    if process.poll() is not None:
                        raise BrowserWorkerUnavailableError(
                            f"Browser worker exited with code {process.returncode}"
                        ) from error
                    raise BrowserWorkerUnavailableError(
                        f"Browser worker timed out during {method}"
                    ) from error
                worker_error = response.get("error")
                if isinstance(worker_error, dict):
                    error_type = worker_error.get("type", "BrowserWorkerError")
                    message = worker_error.get("message", "Browser worker command failed")
                    raise BrowserWorkerError(f"{error_type}: {message}")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise BrowserWorkerError("Browser worker returned an invalid response")
                return result
            finally:
                with self._responses_lock:
                    self._responses.pop(request_id, None)

    def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                response: dict[str, Any] = json.loads(line)
                request_id = response.get("id")
                if not isinstance(request_id, str):
                    continue
                with self._responses_lock:
                    response_queue = self._responses.get(request_id)
                if response_queue is not None:
                    response_queue.put(response)
            except (json.JSONDecodeError, TypeError):
                continue
