from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

from .configuration import load_config, state_dir


ENGINE_URL = os.getenv("CLOUD_BACKUP_ENGINE_URL", "http://backup-engine:8091")
TRIGGER_TIMEOUTS = {
    "backup": 60 * 60 * 13,
    "forget": 60 * 60,
    "prune": 60 * 60 * 7,
}
_IN_FLIGHT_LOCK = Lock()
_IN_FLIGHT: set[str] = set()


def scheduler_state_file() -> Path:
    return state_dir() / "scheduler-state.json"


def load_state() -> dict:
    file_path = scheduler_state_file()
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    scheduler_state_file().write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def should_run(job: dict, now: datetime, last_run: str | None) -> bool:
    if not job.get("enabled"):
        return False
    if now.weekday() not in job.get("days_of_week", []):
        return False
    current_time = now.strftime("%H:%M")
    if current_time != job.get("time"):
        return False
    if last_run == now.strftime("%Y-%m-%dT%H:%M"):
        return False
    return True


def trigger(path: str, payload: dict | None = None, timeout: int = 60 * 60) -> dict:
    request = urllib.request.Request(
        f"{ENGINE_URL}{path}",
        method="POST",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def status() -> dict:
    # The scheduler only needs to know whether a job is already running.
    with urllib.request.urlopen(f"{ENGINE_URL}/engine/runtime", timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def in_flight(name: str) -> bool:
    with _IN_FLIGHT_LOCK:
        return name in _IN_FLIGHT


def mark_in_flight(name: str) -> bool:
    with _IN_FLIGHT_LOCK:
        if name in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(name)
        return True


def clear_in_flight(name: str) -> None:
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT.discard(name)


def run_job(name: str, path: str, state_key: str) -> None:
    try:
        response = trigger(
            path,
            {"tag": "scheduled"} if name == "backup" else {},
            timeout=TRIGGER_TIMEOUTS.get(name, 60 * 60),
        )
        if response.get("ok"):
            state = load_state()
            state[name] = state_key
            save_state(state)
    except Exception:
        # Keep the scheduler alive; the next matching window can retry.
        pass
    finally:
        clear_in_flight(name)


def main() -> None:
    while True:
        try:
            now = datetime.now()
            config = load_config()
            state = load_state()
            status_payload = status()
            current_run = status_payload.get("current_run")
            for name, path in (("backup", "/engine/backup"), ("forget", "/engine/forget"), ("prune", "/engine/prune")):
                job = config["schedule"][name]
                last_run = state.get(name)
                if not should_run(job, now, last_run):
                    continue
                if current_run or in_flight(name):
                    continue
                state_key = now.strftime("%Y-%m-%dT%H:%M")
                if not mark_in_flight(name):
                    continue
                Thread(target=run_job, args=(name, path, state_key), daemon=True).start()
        except Exception:
            # Avoid killing the scheduler loop on transient connectivity or runtime errors.
            pass
        time.sleep(30)


if __name__ == "__main__":
    main()
