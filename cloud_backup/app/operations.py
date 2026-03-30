from __future__ import annotations

import json
import re
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .configuration import load_config, log_dir, rclone_config_path, state_dir
from .runtime import _RUN_LOCK, append_log, begin_run, current_run, end_run, interrupted_run, json_response, run_command, utc_now


def build_restic_env(config: dict[str, Any]) -> dict[str, str]:
    provider = config["provider"]
    return {
        "RESTIC_PASSWORD": provider["restic_password"],
        "RESTIC_REPOSITORY": provider["repository"],
        "RCLONE_CONFIG": str(rclone_config_path()),
        "RESTIC_CACHE_DIR": "/data/restic-cache",
    }


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


def preflight(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    mount_results = check_mounts(cfg)
    source_results = check_sources(cfg)
    remote_result = check_remote_connectivity(cfg) if cfg["security"]["require_remote_connectivity"] else json_response(True, skipped=True)
    repository_result = check_repository_access(cfg)
    disk_health_result = check_disk_health(cfg)

    failures = []
    if any(not item["exists"] or not item["is_dir"] for item in mount_results):
        failures.append("Expected mountpoint missing or not a directory")
    if any(item["critical_failure"] for item in source_results):
        failures.append("Source validation failed")
    if not remote_result["ok"]:
        failures.append("Remote connectivity failed")
    if not disk_health_result["ok"]:
        failures.append("Storage health gate failed")
    if not repository_result["ok"]:
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
    append_log("preflight.jsonl", report)
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
            result = run_command(command, env=build_restic_env(config), timeout=60 * 60 * 12)
            payload = json_response(result.code == 0, action="backup", tag=tag, command=command, stdout=result.stdout, stderr=result.stderr)
            if result.code == 0:
                (state_dir() / "last_successful_backup.txt").write_text(utc_now(), encoding="utf-8")
                notify(config, "success", "Backup concluido", f"Tag: {tag}")
            else:
                run_post_failure_prune(config, "backup")
                notify(config, "error", "Backup falhou", result.stderr[-800:])
            append_log("operations.jsonl", payload)
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
            result = run_command(command, env=build_restic_env(config), timeout=60 * 30)
        payload = json_response(result.code == 0, action="forget", command=command, stdout=result.stdout, stderr=result.stderr)
        append_log("operations.jsonl", payload)
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
            result = run_command(command, env=build_restic_env(config), timeout=60 * 60 * 6)
        payload = json_response(result.code == 0, action="prune", command=command, stdout=result.stdout, stderr=result.stderr)
        append_log("operations.jsonl", payload)
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
    config = load_config()
    snapshots = list_snapshots()
    stats = repository_stats()
    gate = preflight(config)
    last_backup_file = state_dir() / "last_successful_backup.txt"
    last_backup = last_backup_file.read_text(encoding="utf-8").strip() if last_backup_file.exists() else None
    return json_response(
        gate["ok"],
        config=config,
        preflight=gate,
        snapshots=snapshots.get("snapshots", []),
        stats=stats.get("stats", {}),
        last_successful_backup=last_backup,
        current_run=current_run(),
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
    recover_interrupted_backup()
    preflight_result = preflight(load_config())
    return json_response(preflight_result["ok"], details=preflight_result)
