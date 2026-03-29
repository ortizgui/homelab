from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .configuration import load_config, state_dir


ENGINE_URL = os.getenv("CLOUD_BACKUP_ENGINE_URL", "http://backup-engine:8091")


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


def trigger(path: str, payload: dict | None = None) -> None:
    request = urllib.request.Request(
        f"{ENGINE_URL}{path}",
        method="POST",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60 * 60) as response:
        response.read()


def main() -> None:
    while True:
        now = datetime.now()
        config = load_config()
        state = load_state()
        for name, path in (("backup", "/engine/backup"), ("forget", "/engine/forget"), ("prune", "/engine/prune")):
            job = config["schedule"][name]
            last_run = state.get(name)
            if should_run(job, now, last_run):
                trigger(path, {"tag": "scheduled"} if name == "backup" else {})
                state[name] = now.strftime("%Y-%m-%dT%H:%M")
                save_state(state)
        time.sleep(30)


if __name__ == "__main__":
    main()
