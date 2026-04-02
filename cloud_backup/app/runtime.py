from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .configuration import log_dir


_RUN_LOCK = threading.Lock()
_RUN_STATE_LOCK = threading.Lock()
_CURRENT_RUN: dict[str, Any] | None = None


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str
    command: list[str]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_response(ok: bool, **payload: Any) -> dict[str, Any]:
    data = {"ok": ok, "timestamp": utc_now()}
    data.update(payload)
    return data


def current_run_state_file() -> Path:
    return log_dir().parent / "state" / "current-run.json"


def run_command(command: list[str], env: dict[str, str] | None = None, timeout: int = 600) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=merged_env,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            command=command,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        timeout_message = f"Command timed out after {timeout}s: {' '.join(command)}"
        stderr = f"{stderr.rstrip()}\n{timeout_message}".strip()
        return CommandResult(
            code=124,
            stdout=stdout,
            stderr=stderr,
            command=command,
        )


def run_command_streaming(
    command: list[str],
    env: dict[str, str] | None = None,
    timeout: int = 600,
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
        bufsize=1,
    )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def reader(stream: Any, parts: list[str], callback: Callable[[str], None] | None) -> None:
        try:
            for line in iter(stream.readline, ""):
                parts.append(line)
                if callback is not None:
                    callback(line)
        finally:
            stream.close()

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, stdout_parts, on_stdout_line), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, stderr_parts, on_stderr_line), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        code = 124
    finally:
        stdout_thread.join()
        stderr_thread.join()

    if timed_out:
        timeout_message = f"Command timed out after {timeout}s: {' '.join(command)}"
        stderr_parts.append(f"{timeout_message}\n")

    return CommandResult(
        code=code,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        command=command,
    )


def append_log(name: str, payload: dict[str, Any]) -> Path:
    target = log_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return target


def begin_run(action: str, **details: Any) -> dict[str, Any] | None:
    global _CURRENT_RUN
    with _RUN_STATE_LOCK:
        if _CURRENT_RUN is not None:
            return dict(_CURRENT_RUN)
        _CURRENT_RUN = {"action": action, "started_at": utc_now(), "pid": os.getpid(), **details}
        state_file = current_run_state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(_CURRENT_RUN, sort_keys=True) + "\n", encoding="utf-8")
        return None


def update_run_progress(progress: dict[str, Any]) -> None:
    with _RUN_STATE_LOCK:
        if _CURRENT_RUN is None:
            return
        _CURRENT_RUN["progress"] = progress
        state_file = current_run_state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(_CURRENT_RUN, sort_keys=True) + "\n", encoding="utf-8")


def end_run() -> None:
    global _CURRENT_RUN
    with _RUN_STATE_LOCK:
        _CURRENT_RUN = None
        current_run_state_file().unlink(missing_ok=True)


def current_run() -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        return dict(_CURRENT_RUN) if _CURRENT_RUN is not None else None


def interrupted_run() -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        if _CURRENT_RUN is not None:
            return None
        state_file = current_run_state_file()
        if not state_file.exists():
            return None
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        pid = payload.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                return None
            except ProcessLookupError:
                return payload
            except PermissionError:
                return None
        return payload


def list_json_logs(name: str, limit: int = 200) -> list[dict[str, Any]]:
    target = log_dir() / name
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]
