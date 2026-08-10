from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any


class CodexAppServerError(RuntimeError):
    pass


def find_codex_executable() -> str:
    executable = (
        shutil.which("codex.cmd")
        or shutil.which("codex.exe")
        or shutil.which("codex")
    )
    if not executable:
        raise CodexAppServerError("Codex CLI was not found on PATH")
    return executable


def _reader(stream: Any, output: queue.Queue[str | None]) -> None:
    for line in iter(stream.readline, ""):
        output.put(line)
    output.put(None)


class CodexAppServerClient:
    def __init__(
        self,
        *,
        client_name: str = "sitter-harness",
        timeout: float = 30.0,
    ) -> None:
        self.timeout = timeout
        self.client_name = client_name
        self._process: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._raw: list[dict[str, Any]] = []
        self._next_id = 1
        self.initialize_response: dict[str, Any] | None = None

    def __enter__(self) -> "CodexAppServerClient":
        executable = find_codex_executable()
        self._process = subprocess.Popen(
            [executable, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self._process.stdin and self._process.stdout and self._process.stderr
        threading.Thread(
            target=_reader,
            args=(self._process.stdout, self._stdout),
            daemon=True,
        ).start()
        threading.Thread(
            target=lambda: self._stderr_lines.extend(self._process.stderr.readlines()),
            daemon=True,
        ).start()
        self.initialize_response = self.request(
            "initialize",
            {
                "clientInfo": {"name": self.client_name, "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.notify("initialized", {})
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        process = self._process
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            if process.poll() is None:
                process.kill()

    @property
    def raw_messages(self) -> list[dict[str, Any]]:
        return list(self._raw)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_lines)

    @property
    def codex_home(self) -> Path | None:
        result = (self.initialize_response or {}).get("result") or {}
        value = result.get("codexHome")
        return Path(value) if isinstance(value, str) and value else None

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise CodexAppServerError("Codex App Server is not running")
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()
        self._raw.append({"direction": "send", "message": message})

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _next_message(self, *, timeout: float | None = None) -> dict[str, Any]:
        try:
            line = self._stdout.get(timeout=timeout or self.timeout)
        except queue.Empty as error:
            raise CodexAppServerError(
                "timed out waiting for Codex App Server"
            ) from error
        if line is None:
            raise CodexAppServerError(
                "Codex App Server stdout closed unexpectedly"
            )
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise CodexAppServerError(
                f"Codex App Server emitted non-JSON output: {line!r}"
            ) from error
        if not isinstance(message, dict):
            raise CodexAppServerError(
                "Codex App Server emitted a non-object JSON message"
            )
        self._raw.append({"direction": "receive", "message": message})
        return message

    def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._next_message(timeout=timeout)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CodexAppServerError(
                    f"Codex App Server {method} failed: "
                    + json.dumps(message["error"], ensure_ascii=False)
                )
            return message

    def wait_for_notification(
        self,
        method: str,
        *,
        predicate=None,  # type: ignore[no-untyped-def]
        timeout: float | None = None,
        on_notification=None,  # type: ignore[no-untyped-def]
    ) -> dict[str, Any]:
        while True:
            message = self._next_message(timeout=timeout)
            if message.get("method") is not None and on_notification is not None:
                on_notification(message)
            if message.get("method") != method:
                continue
            params = message.get("params") or {}
            if predicate is None or predicate(params):
                return message
