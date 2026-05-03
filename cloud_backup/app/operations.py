from __future__ import annotations

import copy
import json
import re
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .configuration import load_config, log_dir, rclone_config_path, read_rclone_config, state_dir
from .runtime import (
    _RUN_LOCK,
    append_log,
    begin_run,
    current_run,
    end_run,
    interrupted_run,
    json_response,
    list_json_logs,
    read_persisted_run,
    run_command,
    run_command_streaming,
    update_run_progress,
    utc_now,
)


_PREFLIGHT_CACHE: dict[str, Any] | None = None
_PREFLIGHT_CACHE_TIME: float = 0
_PREFLIGHT_CACHE_LOCK = threading.Lock()
PREFLIGHT_CACHE_TTL = 900  # 15 minutes


def build_restic_env(config: dict[str, Any]) -> dict[str, str]:
    provider = config["provider"]
    return {
        "RESTIC_PASSWORD": provider["restic_password"],
        "RESTIC_REPOSITORY": provider["repository"],
        "RCLONE_CONFIG": str(rclone_config_path()),
        "RESTIC_CACHE_DIR": "/data/restic-cache",
    }


def dashboard_cache_path() -> Path:
    return state_dir() / "dashboard-cache.json"


def empty_dashboard_cache() -> dict[str, Any]:
    return {
        "latest_backup": None,
        "latest_preflight": None,
        "remote_quota": None,
        "last_action": None,
        "updated_at": None,
    }


def load_dashboard_cache() -> dict[str, Any]:
    path = dashboard_cache_path()
    if not path.exists():
        return empty_dashboard_cache()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_dashboard_cache()
    merged = empty_dashboard_cache()
    for key, value in payload.items():
        merged[key] = value
    return merged


def save_dashboard_cache(cache: dict[str, Any]) -> dict[str, Any]:
    path = dashboard_cache_path()
    payload = copy.deepcopy(cache)
    payload["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def update_dashboard_cache(**changes: Any) -> dict[str, Any]:
    cache = load_dashboard_cache()
    for key, value in changes.items():
        cache[key] = value
    return save_dashboard_cache(cache)


def mark_dashboard_action(action: str, phase: str, **extra: Any) -> dict[str, Any]:
    return update_dashboard_cache(
        last_action={
            "action": action,
            "phase": phase,
            "timestamp": utc_now(),
            **extra,
        }
    )


def normalize_bandwidth_limit(value: str) -> list[str]:
    raw = value.strip()
    if not raw:
        return []

    parts = raw.split()
    if parts[0] == "--limit-upload":
        if len(parts) != 2:
            raise ValueError("bandwidth_limit must use '--limit-upload <value>'")
        raw = parts[1]
    elif len(parts) != 1:
        raise ValueError("bandwidth_limit must be either '<value>' or '--limit-upload <value>'")

    match = re.fullmatch(r"(?i)(\d+)([kmg])?", raw)
    if not match:
        raise ValueError("bandwidth_limit must be a whole number optionally followed by K, M, or G")

    amount = int(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = {"": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}[suffix]
    bytes_per_second = amount * multiplier
    kib_per_second = max(1, bytes_per_second // 1024)
    return ["--limit-upload", str(kib_per_second)]


def notify(config: dict[str, Any], level: str, title: str, details: str) -> None:
    notifications = config["notifications"]
    should_send = (
        (level == "error" and notifications.get("notify_on_failure"))
        or (level == "success" and notifications.get("notify_on_success"))
        or level == "info"
    )
    if not should_send:
        return
    message = f"[{config['general']['instance_name']}] {title}\n{details}".strip()
    if notifications.get("telegram_bot_token") and notifications.get("telegram_chat_id"):
        token = notifications["telegram_bot_token"]
        chat_id = notifications["telegram_chat_id"]
        data = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": message,
            }
        ).encode("utf-8")
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=data,
                    method="POST",
                ),
                timeout=10,
            ).read()
        except Exception:
            pass
    if notifications.get("webhook_url"):
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    notifications["webhook_url"],
                    data=json.dumps({"text": message, "level": level}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=10,
            ).read()
        except Exception:
            pass


def parse_restic_summary(stdout: str) -> dict[str, Any] | None:
    summary = None
    for line in stdout.splitlines():
        progress = parse_restic_progress_line(line)
        if progress and progress.get("message_type") == "summary":
            summary = progress
    return summary


def format_bytes(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    amount = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} PiB"


def format_duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    total_seconds = max(0, int(round(float(value))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def snapshot_overview(config: dict[str, Any]) -> dict[str, Any]:
    result = run_command(["restic", "snapshots", "--json"], env=build_restic_env(config), timeout=120)
    snapshots = json.loads(result.stdout) if result.code == 0 and result.stdout.strip() else []
    latest_snapshot = snapshots[-1] if snapshots else {}
    return {
        "ok": result.code == 0,
        "count": len(snapshots),
        "latest_id": latest_snapshot.get("short_id") or latest_snapshot.get("id"),
        "stderr": result.stderr,
    }


def build_backup_notification_details(
    config: dict[str, Any],
    tag: str,
    result: Any,
    summary: dict[str, Any] | None,
    snapshot_info: dict[str, Any] | None = None,
    post_failure_prune: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"Tag: {tag}",
        f"Repositorio: {config['provider']['repository']}",
    ]
    if summary:
        lines.extend(
            [
                f"Snapshot: {summary.get('snapshot_id') or '-'}",
                f"Arquivos processados: {summary.get('total_files_processed') if summary.get('total_files_processed') is not None else '-'}",
                f"Arquivos novos: {summary.get('files_new') if summary.get('files_new') is not None else '-'}",
                f"Arquivos alterados: {summary.get('files_changed') if summary.get('files_changed') is not None else '-'}",
                f"Dados enviados: {format_bytes(summary.get('data_added'))}",
                f"Dados lidos: {format_bytes(summary.get('total_bytes_processed'))}",
                f"Duracao: {format_duration(summary.get('total_duration'))}",
            ]
        )
    if snapshot_info:
        count = snapshot_info.get("count")
        lines.append(f"Snapshots no repositorio: {count if count is not None else '-'}")
    if getattr(result, "code", 1) != 0:
        stderr = (getattr(result, "stderr", "") or "").strip()
        failure_reason = stderr.splitlines()[-1] if stderr else "Falha sem detalhe adicional no stderr."
        lines.append(f"Motivo: {failure_reason}")
        if post_failure_prune is not None:
            lines.append(f"Prune de recuperacao: {'ok' if post_failure_prune.get('ok') else 'falhou'}")
    elif snapshot_info and snapshot_info.get("ok") is False and snapshot_info.get("stderr"):
        lines.append("Observacao: nao foi possivel atualizar a contagem de snapshots apos o backup.")
    return "\n".join(lines)


def safe_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in config["sources"] if source.get("enabled")]


def validate_path_within_roots(config: dict[str, Any], candidate: str) -> None:
    roots = [Path(root).resolve() for root in config["general"]["authorized_roots"]]
    path = Path(candidate).resolve()
    for root in roots:
        try:
            path.relative_to(root)
            return
        except ValueError:
            continue
    raise ValueError("Path is outside authorized roots")


def browse_path(config: dict[str, Any], requested_path: str | None) -> dict[str, Any]:
    base_path = requested_path or config["general"]["authorized_roots"][0]
    validate_path_within_roots(config, base_path)
    path = Path(base_path)
    if not path.exists() or not path.is_dir():
        raise ValueError("Requested path does not exist or is not a directory")
    entries = []
    for entry in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if entry.is_dir():
            entries.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "type": "directory",
                }
            )
    return json_response(True, path=str(path), entries=entries)


def restic_repository_initialized(config: dict[str, Any]) -> bool:
    result = run_command(["restic", "cat", "config"], env=build_restic_env(config), timeout=30)
    return result.code == 0


def init_repository(config: dict[str, Any]) -> dict[str, Any]:
    if restic_repository_initialized(config):
        return json_response(True, changed=False, message="Repository already initialized")
    result = run_command(["restic", "init"], env=build_restic_env(config), timeout=120)
    if result.code != 0:
        return json_response(False, message="Repository initialization failed", stdout=result.stdout, stderr=result.stderr)
    return json_response(True, changed=True, stdout=result.stdout)


def check_remote_connectivity(config: dict[str, Any]) -> dict[str, Any]:
    remote_name = config["provider"]["remote_name"]
    result = run_command(["rclone", "lsd", f"{remote_name}:"], env={"RCLONE_CONFIG": str(rclone_config_path())}, timeout=30)
    return json_response(
        result.code == 0,
        remote=remote_name,
        stdout=result.stdout,
        stderr=result.stderr,
        message="Remote reachable" if result.code == 0 else "Remote connectivity failed",
    )


def remote_storage_quota(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    remote_name = cfg["provider"]["remote_name"]
    previous = load_dashboard_cache().get("remote_quota")
    result = run_command(
        ["rclone", "about", f"{remote_name}:", "--json"],
        env={"RCLONE_CONFIG": str(rclone_config_path())},
        timeout=30,
    )
    quota = {}
    if result.code == 0 and result.stdout.strip():
        try:
            quota = json.loads(result.stdout)
        except json.JSONDecodeError:
            quota = {}
    payload = json_response(
        result.code == 0,
        remote=remote_name,
        quota=quota,
        stdout=result.stdout,
        stderr=result.stderr,
        message="Remote quota loaded" if result.code == 0 else "Remote quota unavailable",
    )
    cached_quota = {
        "ok": payload["ok"],
        "remote": remote_name,
        "quota": quota,
        "message": payload["message"],
        "timestamp": payload["timestamp"],
        "stale": False,
    }
    if payload["ok"] or load_dashboard_cache().get("remote_quota") is None:
        update_dashboard_cache(remote_quota=cached_quota)
    elif previous:
        stale_quota = copy.deepcopy(previous)
        stale_quota["stale"] = True
        stale_quota["message"] = payload["message"]
        update_dashboard_cache(remote_quota=stale_quota)
        return json_response(
            True,
            remote=stale_quota.get("remote", remote_name),
            quota=stale_quota.get("quota", {}),
            message=stale_quota.get("message", "Remote quota cache loaded"),
            stale=True,
        )
    return payload


def check_repository_access(config: dict[str, Any]) -> dict[str, Any]:
    env = build_restic_env(config)
    config_result = run_command(["restic", "cat", "config"], env=env, timeout=30)
    if config_result.code == 0:
        return json_response(True, initialized=True, message="Repository is accessible")
    snapshots_result = run_command(["restic", "snapshots", "--json"], env=env, timeout=60)
    if snapshots_result.code == 0:
        return json_response(True, initialized=True, message="Repository is accessible")
    repository = config["provider"]["repository"]
    stderr = f"{config_result.stderr}\n{snapshots_result.stderr}".strip()
    stdout = f"{config_result.stdout}\n{snapshots_result.stdout}".strip()
    initialized = not any(
        token in stderr.lower()
        for token in [
            "is there a repository at the following location",
            "does not exist",
            "no such file or directory",
            "404",
            "not found",
        ]
    )
    return json_response(
        False,
        initialized=initialized,
        repository=repository,
        stdout=stdout,
        stderr=stderr,
        message="Repository access failed",
    )


def check_mounts(config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for mount in config["security"]["expected_mounts"]:
        path = Path(mount)
        results.append(
            {
                "path": mount,
                "exists": path.exists(),
                "is_dir": path.is_dir(),
            }
        )
    return results


def check_disk_health(config: dict[str, Any]) -> dict[str, Any]:
    security = config["security"]
    blocker = security.get("disk_health_blocker_file") or ""
    if blocker and Path(blocker).exists():
        return json_response(False, message=f"Disk health blocker file present: {blocker}")

    status_file = security.get("disk_health_status_file") or ""
    if status_file and Path(status_file).exists():
        try:
            payload = json.loads(Path(status_file).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return json_response(False, message=f"Disk health status file is invalid JSON: {exc}")
        status = str(payload.get("status", "unknown")).lower()
        if status not in {"ok", "healthy", "pass"}:
            return json_response(False, message=f"Disk health reported {status}", details=payload)
        return json_response(True, message="Disk health status file is healthy", details=payload)

    mdstat_file = Path(security.get("mdstat_file") or "")
    if mdstat_file.exists():
        mdstat_text = mdstat_file.read_text(encoding="utf-8")
        degraded = any("[" in line and "_" in line for line in mdstat_text.splitlines())
        if degraded:
            return json_response(False, message="mdstat indicates degraded RAID", details={"mdstat_excerpt": mdstat_text[:500]})

    return json_response(True, message="No storage degradation detected")


def check_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for source in safe_sources(config):
        path = Path(source["path"])
        exists = path.exists()
        readable = exists and os_access_read(path)
        non_empty = exists and any(path.iterdir()) if exists and path.is_dir() else False
        blocked_empty = exists and path.is_dir() and not non_empty and not source.get("allow_empty", False)
        results.append(
            {
                "path": source["path"],
                "exists": exists,
                "readable": readable,
                "non_empty": non_empty,
                "allow_empty": source.get("allow_empty", False),
                "critical_failure": (not exists) or (not readable) or blocked_empty,
            }
        )
    return results


def os_access_read(path: Path) -> bool:
    try:
        list(path.iterdir()) if path.is_dir() else path.open("rb").close()
        return True
    except Exception:
        return False


def _get_preflight_cache() -> dict[str, Any] | None:
    global _PREFLIGHT_CACHE, _PREFLIGHT_CACHE_TIME
    with _PREFLIGHT_CACHE_LOCK:
        if _PREFLIGHT_CACHE is None:
            return None
        if time.time() - _PREFLIGHT_CACHE_TIME > PREFLIGHT_CACHE_TTL:
            _PREFLIGHT_CACHE = None
            return None
        return dict(_PREFLIGHT_CACHE)


def _set_preflight_cache(payload: dict[str, Any]) -> None:
    global _PREFLIGHT_CACHE, _PREFLIGHT_CACHE_TIME
    with _PREFLIGHT_CACHE_LOCK:
        _PREFLIGHT_CACHE = copy.deepcopy(payload)
        _PREFLIGHT_CACHE_TIME = time.time()


def _invalidate_preflight_cache() -> None:
    global _PREFLIGHT_CACHE, _PREFLIGHT_CACHE_TIME
    with _PREFLIGHT_CACHE_LOCK:
        _PREFLIGHT_CACHE = None
        _PREFLIGHT_CACHE_TIME = 0


def check_rclone_token_expiry() -> dict[str, Any]:
    config_text = read_rclone_config()
    if not config_text.strip():
        return {"ok": True, "message": "No rclone config to check"}
    match = re.search(r'token\s*=\s*(\{.*?\})', config_text, re.DOTALL)
    if not match:
        return {"ok": True, "message": "No token field in rclone config (may use newer format)"}
    try:
        token = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"ok": False, "message": "Invalid token JSON in rclone config"}
    expiry_str = token.get("expiry")
    if not expiry_str:
        return {"ok": True, "message": "No expiry in token"}
    try:
        expiry = datetime.fromisoformat(expiry_str)
    except (ValueError, TypeError):
        return {"ok": False, "message": f"Cannot parse token expiry: {expiry_str}"}
    now = datetime.now(timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    remaining_secs = (expiry - now).total_seconds()
    days_remaining = remaining_secs / 86400
    if days_remaining < 0:
        return {"ok": False, "expired": True, "days": round(abs(days_remaining), 1), "message": f"Token expired {abs(days_remaining):.1f} days ago. Run: rclone config reconnect gdrive:"}
    if days_remaining < 7:
        return {"ok": True, "warning": True, "days": round(days_remaining, 1), "message": f"Token expires in {days_remaining:.1f} days. Refresh soon."}
    return {"ok": True, "days": round(days_remaining, 1), "message": f"Token valid for {days_remaining:.1f} more days"}


def preflight(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mark_dashboard_action("preflight", "started")
    cfg = config or load_config()

    mount_results = check_mounts(cfg)
    source_results = check_sources(cfg)
    disk_health_result = check_disk_health(cfg)

    failures = []
    if any(not item["exists"] or not item["is_dir"] for item in mount_results):
        failures.append("Expected mountpoint missing or not a directory")
    if any(item["critical_failure"] for item in source_results):
        failures.append("Source validation failed")
    if not disk_health_result["ok"]:
        failures.append("Storage health gate failed")

    remote_result: dict[str, Any]
    repository_result: dict[str, Any]
    token_warning: dict[str, Any] | None = None

    cached = _get_preflight_cache()
    if cached and not failures:
        remote_result = cached["remote_result"]
        repository_result = cached["repository_result"]
    else:
        if not failures:
            remote_result = check_remote_connectivity(cfg) if cfg["security"]["require_remote_connectivity"] else json_response(True, skipped=True)
            repository_result = check_repository_access(cfg)
            _set_preflight_cache({
                "remote_result": remote_result,
                "repository_result": repository_result,
            })
            token_warning = check_rclone_token_expiry()
        else:
            remote_result = json_response(True, skipped=True)
            repository_result = json_response(True, skipped=True)

    if not remote_result.get("ok") and "skipped" not in remote_result:
        failures.append("Remote connectivity failed")
    if not repository_result.get("ok"):
        failures.append("Repository access failed")

    report = json_response(
        len(failures) == 0,
        message="Preflight passed" if not failures else "Preflight blocked operation",
        failures=failures,
        mount_results=mount_results,
        source_results=source_results,
        remote_result=remote_result,
        repository_result=repository_result,
        disk_health_result=disk_health_result,
    )
    if token_warning and not token_warning.get("ok"):
        report["token_warning"] = token_warning

    append_log("preflight.jsonl", report)
    update_dashboard_cache(latest_preflight=report)
    mark_dashboard_action("preflight", "completed", ok=report["ok"])
    return report


def build_backup_command(config: dict[str, Any], tag: str) -> list[str]:
    command = [
        "restic",
        "backup",
        "--skip-if-unchanged",
        "--one-file-system",
        "--tag",
        tag,
        "--json",
    ]
    for exclusion in config["exclusions"]:
        command.extend(["--exclude", exclusion])
    bandwidth_limit = config["limits"].get("bandwidth_limit", "").strip()
    if bandwidth_limit:
        command.extend(normalize_bandwidth_limit(bandwidth_limit))
    for source in safe_sources(config):
        command.append(source["path"])
    return command


def parse_restic_progress_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    message_type = payload.get("message_type")
    if message_type == "status":
        current_files = payload.get("current_files") or []
        return {
            "phase": "running",
            "message_type": message_type,
            "percent_done": payload.get("percent_done"),
            "seconds_elapsed": payload.get("seconds_elapsed"),
            "seconds_remaining": payload.get("seconds_remaining"),
            "total_files": payload.get("total_files"),
            "files_done": payload.get("files_done"),
            "total_bytes": payload.get("total_bytes"),
            "bytes_done": payload.get("bytes_done"),
            "current_files": current_files,
            "current_file": current_files[0] if current_files else None,
        }
    if message_type == "summary":
        return {
            "phase": "finalizing",
            "message_type": message_type,
            "files_new": payload.get("files_new"),
            "files_changed": payload.get("files_changed"),
            "files_unmodified": payload.get("files_unmodified"),
            "dirs_new": payload.get("dirs_new"),
            "dirs_changed": payload.get("dirs_changed"),
            "dirs_unmodified": payload.get("dirs_unmodified"),
            "data_blobs": payload.get("data_blobs"),
            "tree_blobs": payload.get("tree_blobs"),
            "data_added": payload.get("data_added"),
            "total_files_processed": payload.get("total_files_processed"),
            "total_bytes_processed": payload.get("total_bytes_processed"),
            "total_duration": payload.get("total_duration"),
            "snapshot_id": payload.get("snapshot_id"),
        }
    return None


def run_post_failure_prune(config: dict[str, Any], trigger_action: str) -> dict[str, Any]:
    command = ["restic", "prune", "--json"]
    result = run_command(command, env=build_restic_env(config), timeout=60 * 60 * 6)
    payload = json_response(
        result.code == 0,
        action="prune",
        phase="post-failure",
        trigger_action=trigger_action,
        command=command,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    append_log("operations.jsonl", payload)
    mark_dashboard_action("prune", "completed", ok=payload["ok"], trigger_action=trigger_action)
    return payload


def unlock_repository(remove_all: bool = True) -> dict[str, Any]:
    mark_dashboard_action("unlock", "started", remove_all=remove_all)
    config = load_config()
    command = ["restic", "unlock"]
    if remove_all:
        command.append("--remove-all")
    result = run_command(command, env=build_restic_env(config), timeout=120)
    payload = json_response(
        result.code == 0,
        action="unlock",
        command=command,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    append_log("operations.jsonl", payload)
    mark_dashboard_action("unlock", "completed", ok=payload["ok"], remove_all=remove_all)
    return payload


def recover_interrupted_backup() -> dict[str, Any] | None:
    interrupted = interrupted_run()
    if interrupted is None:
        return None

    config = load_config()
    payload = run_post_failure_prune(config, interrupted.get("action", "unknown"))
    recovery_payload = json_response(
        payload["ok"],
        action="recovery",
        phase="startup-prune",
        interrupted_run=interrupted,
        prune=payload,
    )
    append_log("operations.jsonl", recovery_payload)
    mark_dashboard_action("recovery", "completed", ok=recovery_payload["ok"])
    end_run()
    return recovery_payload


def run_backup(tag: str = "manual") -> dict[str, Any]:
    recover_interrupted_backup()
    config = load_config()
    gate = preflight(config)
    if not gate["ok"]:
        notify(config, "error", "Backup bloqueado", "\n".join(gate["failures"]))
        return gate

    active_run = begin_run("backup", tag=tag)
    if active_run is not None:
        return json_response(False, message=f"{active_run['action']} already running", current_run=active_run)

    with _RUN_LOCK:
        mark_dashboard_action("backup", "started", tag=tag)
        try:
            repository_status = check_repository_access(config)
            if not repository_status["ok"] and not repository_status.get("initialized", False):
                init_result = init_repository(config)
                if not init_result["ok"]:
                    append_log("operations.jsonl", init_result)
                    notify(config, "error", "Inicializacao do repositorio falhou", init_result.get("stderr", ""))
                    return init_result
            command = build_backup_command(config, tag)
            append_log(
                "operations.jsonl",
                json_response(
                    True,
                    action="backup",
                    phase="started",
                    tag=tag,
                    command=command,
                ),
            )
            update_run_progress(
                {
                    "phase": "starting",
                    "message_type": "status",
                    "percent_done": 0,
                    "files_done": 0,
                    "bytes_done": 0,
                    "current_file": None,
                    "current_files": [],
                }
            )

            def handle_backup_stdout(line: str) -> None:
                progress = parse_restic_progress_line(line)
                if progress is not None:
                    update_run_progress(progress)

            result = run_command_streaming(
                command,
                env=build_restic_env(config),
                timeout=60 * 60 * 12,
                on_stdout_line=handle_backup_stdout,
            )
            payload = json_response(result.code == 0, action="backup", tag=tag, command=command, stdout=result.stdout, stderr=result.stderr)
            summary = parse_restic_summary(result.stdout)
            if result.code == 0:
                (state_dir() / "last_successful_backup.txt").write_text(utc_now(), encoding="utf-8")
                update_dashboard_cache(latest_backup=latest_backup_result())
                remote_storage_quota(config)
                notify(
                    config,
                    "success",
                    "Backup concluido",
                    build_backup_notification_details(
                        config,
                        tag,
                        result,
                        summary,
                        snapshot_info=snapshot_overview(config),
                    ),
                )
            else:
                post_failure_prune = run_post_failure_prune(config, "backup")
                notify(
                    config,
                    "error",
                    "Backup falhou",
                    build_backup_notification_details(
                        config,
                        tag,
                        result,
                        summary,
                        snapshot_info=snapshot_overview(config),
                        post_failure_prune=post_failure_prune,
                    ),
                )
            append_log("operations.jsonl", payload)
            update_dashboard_cache(latest_backup=latest_backup_result())
            mark_dashboard_action("backup", "completed", ok=payload["ok"], tag=tag)
            return payload
        finally:
            end_run()


def run_forget() -> dict[str, Any]:
    recover_interrupted_backup()
    config = load_config()
    gate = preflight(config)
    if not gate["ok"]:
        notify(config, "error", "Forget bloqueado", "\n".join(gate["failures"]))
        return gate
    retention = config["retention"]
    command = [
        "restic",
        "forget",
        "--keep-last",
        str(retention["keep_last"]),
        "--keep-daily",
        str(retention["keep_daily"]),
        "--keep-weekly",
        str(retention["keep_weekly"]),
        "--keep-monthly",
        str(retention["keep_monthly"]),
        "--json",
    ]
    active_run = begin_run("forget")
    if active_run is not None:
        return json_response(False, message=f"{active_run['action']} already running", current_run=active_run)

    try:
        with _RUN_LOCK:
            mark_dashboard_action("forget", "started")
            result = run_command(command, env=build_restic_env(config), timeout=60 * 30)
        payload = json_response(result.code == 0, action="forget", command=command, stdout=result.stdout, stderr=result.stderr)
        append_log("operations.jsonl", payload)
        remote_storage_quota(config)
        mark_dashboard_action("forget", "completed", ok=payload["ok"])
        return payload
    finally:
        end_run()


def run_prune() -> dict[str, Any]:
    recover_interrupted_backup()
    config = load_config()
    gate = preflight(config)
    if not gate["ok"]:
        notify(config, "error", "Prune bloqueado", "\n".join(gate["failures"]))
        return gate
    command = ["restic", "prune", "--json"]
    active_run = begin_run("prune")
    if active_run is not None:
        return json_response(False, message=f"{active_run['action']} already running", current_run=active_run)

    try:
        with _RUN_LOCK:
            mark_dashboard_action("prune", "started")
            result = run_command(command, env=build_restic_env(config), timeout=60 * 60 * 6)
        payload = json_response(result.code == 0, action="prune", command=command, stdout=result.stdout, stderr=result.stderr)
        append_log("operations.jsonl", payload)
        remote_storage_quota(config)
        mark_dashboard_action("prune", "completed", ok=payload["ok"])
        return payload
    finally:
        end_run()


def list_snapshots() -> dict[str, Any]:
    config = load_config()
    result = run_command(["restic", "snapshots", "--json"], env=build_restic_env(config), timeout=120)
    snapshots = json.loads(result.stdout) if result.code == 0 and result.stdout.strip() else []
    return json_response(result.code == 0, snapshots=snapshots, stderr=result.stderr)


def repository_stats() -> dict[str, Any]:
    config = load_config()
    result = run_command(["restic", "stats", "--mode", "raw-data", "--json"], env=build_restic_env(config), timeout=120)
    stats = json.loads(result.stdout) if result.code == 0 and result.stdout.strip() else {}
    return json_response(result.code == 0, stats=stats, stderr=result.stderr)


def restore_snapshot(snapshot_id: str, target: str, include_path: str | None = None) -> dict[str, Any]:
    config = load_config()
    target_path = Path(target)
    restore_root = Path(config["general"]["restore_root"]).resolve()
    target_resolved = target_path.resolve()
    try:
        target_resolved.relative_to(restore_root)
    except ValueError as exc:
        raise ValueError("Restore target must stay under restore_root") from exc
    if target_path.exists():
        raise ValueError("Restore target already exists")
    target_path.mkdir(parents=True, exist_ok=False)

    command = ["restic", "restore", snapshot_id, "--target", str(target_path)]
    if include_path:
        command.extend(["--include", include_path])
    result = run_command(command, env=build_restic_env(config), timeout=60 * 60 * 12)
    payload = json_response(result.code == 0, action="restore", snapshot_id=snapshot_id, target=str(target_path), stdout=result.stdout, stderr=result.stderr)
    append_log("operations.jsonl", payload)
    return payload


def list_logs(limit: int = 200) -> dict[str, Any]:
    files = []
    for item in sorted(log_dir().glob("*.jsonl")):
        files.append({"name": item.name, "size": item.stat().st_size})
    operations = []
    ops_file = log_dir() / "operations.jsonl"
    if ops_file.exists():
        operations = [json.loads(line) for line in ops_file.read_text(encoding="utf-8").splitlines()[-limit:] if line.strip()]
    return json_response(True, files=files, operations=operations)


def latest_backup_result(limit: int = 400) -> dict[str, Any] | None:
    operations = list_json_logs("operations.jsonl", limit=limit)
    latest: dict[str, Any] | None = None
    for entry in operations:
        if entry.get("action") == "backup" and "ok" in entry:
            latest = entry
    if latest is None:
        return None

    summary = parse_restic_summary(latest.get("stdout") or "")

    detail = (latest.get("stderr") or "").strip()
    if detail:
        detail = detail.splitlines()[-1]
    elif latest.get("stdout"):
        detail = "Backup finalizado e registrado no log."
    else:
        detail = ""

    return {
        "ok": latest.get("ok"),
        "tag": latest.get("tag"),
        "timestamp": latest.get("timestamp"),
        "snapshot_id": summary.get("snapshot_id") if summary else None,
        "total_bytes_processed": summary.get("total_bytes_processed") if summary else None,
        "total_files_processed": summary.get("total_files_processed") if summary else None,
        "data_added": summary.get("data_added") if summary else None,
        "total_duration": summary.get("total_duration") if summary else None,
        "files_new": summary.get("files_new") if summary else None,
        "files_changed": summary.get("files_changed") if summary else None,
        "detail": detail,
    }


def latest_preflight_result(limit: int = 200) -> dict[str, Any] | None:
    entries = list_json_logs("preflight.jsonl", limit=limit)
    return entries[-1] if entries else None


def dashboard_summary() -> dict[str, Any]:
    runtime = runtime_status()
    cache = load_dashboard_cache()
    return json_response(
        True,
        current_run=runtime.get("current_run"),
        last_successful_backup=runtime.get("last_successful_backup"),
        latest_backup=cache.get("latest_backup") or latest_backup_result(),
        latest_preflight=cache.get("latest_preflight") or latest_preflight_result(),
        last_action=cache.get("last_action"),
        cache_updated_at=cache.get("updated_at"),
    )


def cached_dashboard_summary() -> dict[str, Any]:
    cache = load_dashboard_cache()
    last_backup_file = state_dir() / "last_successful_backup.txt"
    last_backup = last_backup_file.read_text(encoding="utf-8").strip() if last_backup_file.exists() else None
    return json_response(
        True,
        current_run=read_persisted_run(),
        last_successful_backup=last_backup,
        latest_backup=cache.get("latest_backup"),
        latest_preflight=cache.get("latest_preflight"),
        last_action=cache.get("last_action"),
        cache_updated_at=cache.get("updated_at"),
        remote_quota=cache.get("remote_quota", {}),
    )


def runtime_status() -> dict[str, Any]:
    last_backup_file = state_dir() / "last_successful_backup.txt"
    last_backup = last_backup_file.read_text(encoding="utf-8").strip() if last_backup_file.exists() else None
    return json_response(
        True,
        current_run=current_run(),
        last_successful_backup=last_backup,
    )


def status() -> dict[str, Any]:
    recover_interrupted_backup()
    last_backup_file = state_dir() / "last_successful_backup.txt"
    last_backup = last_backup_file.read_text(encoding="utf-8").strip() if last_backup_file.exists() else None
    cache = load_dashboard_cache()
    gate = cache.get("latest_preflight") or preflight()
    return json_response(
        gate["ok"],
        preflight=gate,
        last_successful_backup=last_backup,
        current_run=current_run(),
        latest_backup=cache.get("latest_backup"),
        last_action=cache.get("last_action"),
    )


def export_config_bundle() -> dict[str, Any]:
    config = load_config()
    payload = {"schema_version": config["schema_version"], "config": config}
    return json_response(True, bundle=payload)


def import_config_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    config = bundle.get("config")
    if not isinstance(config, dict):
        raise ValueError("Bundle must include config")
    save_config(config)
    return json_response(True, config=config)


def prune_old_logs() -> None:
    load_config()


def healthcheck() -> dict[str, Any]:
    try:
        load_config()
    except Exception as exc:
        return json_response(False, message=f"Configuration load failed: {exc}")

    runtime = runtime_status()
    return json_response(
        True,
        details={
            "service": "backup-engine",
            "current_run": runtime.get("current_run"),
            "last_successful_backup": runtime.get("last_successful_backup"),
        },
    )
