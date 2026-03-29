from __future__ import annotations

import json
import os
import subprocess
import threading
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


def run_command(command: list[str], env: dict[str, str] | None = None, timeout: int = 600) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
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
        _CURRENT_RUN = {"action": action, "started_at": utc_now(), **details}
        return None


def end_run() -> None:
    global _CURRENT_RUN
    with _RUN_STATE_LOCK:
        _CURRENT_RUN = None


def current_run() -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        return dict(_CURRENT_RUN) if _CURRENT_RUN is not None else None


def list_json_logs(name: str, limit: int = 200) -> list[dict[str, Any]]:
    target = log_dir() / name
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]
