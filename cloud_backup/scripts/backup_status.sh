#!/bin/bash

set -euo pipefail

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "docker compose nao encontrado" >&2
  exit 1
fi

run_compose() {
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" "$@"
}

run_compose exec -T backup-engine python3 - <<'PY'
import json
from pathlib import Path

state_file = Path("/data/state/current-run.json")
logs_file = Path("/data/logs/operations.jsonl")
success_file = Path("/data/state/last_successful_backup.txt")


def fmt_bytes(value):
    if not isinstance(value, (int, float)) or value < 0:
        return None
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0 or size >= 100:
        return f"{size:.0f} {units[unit]}"
    if size >= 10:
        return f"{size:.1f} {units[unit]}"
    return f"{size:.2f} {units[unit]}"


def fmt_percent(value):
    if not isinstance(value, (int, float)):
        return None
    return f"{value * 100:.2f}%"


def fmt_duration(value):
    if not isinstance(value, (int, float)) or value < 0:
        return None
    total = int(round(value))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def load_latest_backup_entry():
    if not logs_file.exists():
        return None
    latest = None
    for line in logs_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("action") == "backup" and "ok" in payload:
            latest = payload
    return latest


def parse_backup_summary(entry):
    stdout = entry.get("stdout") or ""
    summary = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("message_type") == "summary":
            summary = payload
    return summary


if state_file.exists():
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    progress = payload.get("progress") or {}
    print("STATUS: RUNNING")
    print(f"ACTION: {payload.get('action', 'unknown')}")
    print(f"TAG: {payload.get('tag', '-')}")
    print(f"STARTED_AT: {payload.get('started_at', '-')}")
    if progress:
        print(f"PHASE: {progress.get('phase', '-')}")
        percent = fmt_percent(progress.get("percent_done"))
        if percent:
            print(f"PROGRESS: {percent}")
        files_done = progress.get("files_done")
        total_files = progress.get("total_files")
        if isinstance(files_done, int):
            if isinstance(total_files, int):
                print(f"FILES: {files_done}/{total_files}")
            else:
                print(f"FILES: {files_done}")
        bytes_done = fmt_bytes(progress.get("bytes_done"))
        total_bytes = fmt_bytes(progress.get("total_bytes"))
        if bytes_done:
            if total_bytes:
                print(f"DATA: {bytes_done}/{total_bytes}")
            else:
                print(f"DATA: {bytes_done}")
        elapsed = fmt_duration(progress.get("seconds_elapsed"))
        remaining = fmt_duration(progress.get("seconds_remaining"))
        if elapsed:
            print(f"ELAPSED: {elapsed}")
        if remaining:
            print(f"ETA: {remaining}")
        print(f"CURRENT_FILE: {progress.get('current_file') or '-'}")
    raise SystemExit(0)

latest = load_latest_backup_entry()
if latest is not None:
    print(f"STATUS: {'SUCCESS' if latest.get('ok') else 'FAILED'}")
    print(f"TAG: {latest.get('tag', '-')}")
    print(f"TIMESTAMP: {latest.get('timestamp', '-')}")
    if success_file.exists():
        print(f"LAST_SUCCESSFUL_BACKUP: {success_file.read_text(encoding='utf-8').strip()}")
    summary = parse_backup_summary(latest)
    if summary:
        total_processed = fmt_bytes(summary.get("total_bytes_processed"))
        if total_processed:
            print(f"TOTAL_PROCESSED: {total_processed}")
        total_files = summary.get("total_files_processed")
        if isinstance(total_files, int):
            print(f"FILES_PROCESSED: {total_files}")
        snapshot_id = summary.get("snapshot_id")
        if snapshot_id:
            print(f"SNAPSHOT_ID: {snapshot_id}")
        data_added = fmt_bytes(summary.get("data_added"))
        if data_added:
            print(f"DATA_ADDED: {data_added}")
    stderr = (latest.get("stderr") or "").strip()
    if stderr:
        print(f"DETAIL: {stderr.splitlines()[-1][:240]}")
    else:
        stdout = (latest.get("stdout") or "").strip()
        if stdout:
            print("DETAIL: backup finalizado e registrado no log")
    raise SystemExit(0)

print("STATUS: UNKNOWN")
print("DETAIL: nenhum backup em execucao e nenhum resultado anterior encontrado.")
PY
