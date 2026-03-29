from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_config() -> dict[str, Any]:
    primary_root = os.getenv("PRIMARY_SOURCE_ROOT", "/source/raid1")
    secondary_root = os.getenv("SECONDARY_SOURCE_ROOT", "/source/m2")
    repository = os.getenv("RESTIC_REPOSITORY", "rclone:gdrive:/backups/restic")
    password = os.getenv("RESTIC_PASSWORD", "")
    timezone = os.getenv("TZ", "America/Sao_Paulo")
    primary_sources = [
        {"path": f"{primary_root}/academic", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/backups", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/documents", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/media", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/onedrive-import", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/personal", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/professional", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/projects", "enabled": True, "allow_empty": True},
        {"path": f"{primary_root}/shared", "enabled": True, "allow_empty": False},
        {"path": f"{primary_root}/software", "enabled": True, "allow_empty": False},
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "general": {
            "instance_name": os.getenv("CLOUD_BACKUP_HOSTNAME", "homelab"),
            "timezone": timezone,
            "authorized_roots": [primary_root, secondary_root],
            "restore_root": "/data/restore",
            "log_retention_days": 30,
        },
        "provider": {
            "type": "google-drive",
            "remote_name": "gdrive",
            "repository": repository,
            "restic_password": password,
            "rclone_config": "",
        },
        "sources": primary_sources + [{"path": secondary_root, "enabled": False, "allow_empty": True}],
        "exclusions": [
            "*.tmp",
            "*.cache",
            "__pycache__",
            ".DS_Store",
            "Thumbs.db",
        ],
        "schedule": {
            "backup": {"enabled": True, "days_of_week": [0, 3], "time": "03:00"},
            "forget": {"enabled": True, "days_of_week": [6], "time": "04:00"},
            "prune": {"enabled": False, "days_of_week": [6], "time": "05:00"},
        },
        "retention": {
            "keep_last": 7,
            "keep_daily": 14,
            "keep_weekly": 8,
            "keep_monthly": 3,
        },
        "notifications": {
            "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "webhook_url": os.getenv("WEBHOOK_URL", ""),
            "notify_on_success": _env_bool("NOTIFY_ON_SUCCESS", True),
            "notify_on_failure": _env_bool("NOTIFY_ON_FAILURE", True),
        },
        "security": {
            "require_remote_connectivity": True,
            "abort_on_unexpected_empty_source": True,
            "expected_mounts": [primary_root, secondary_root],
            "disk_health_status_file": os.getenv("CLOUD_BACKUP_DISK_HEALTH_FILE", "/health/disk-health.json"),
            "disk_health_blocker_file": os.getenv("CLOUD_BACKUP_DISK_HEALTH_BLOCKER_FILE", ""),
            "mdstat_file": os.getenv("CLOUD_BACKUP_MDSTAT_FILE", "/host/proc/mdstat"),
        },
        "limits": {
            "bandwidth_limit": os.getenv("BANDWIDTH_LIMIT", ""),
            "capacity_alert_threshold_percent": 80,
        },
    }


def config_path() -> Path:
    return Path(os.getenv("CLOUD_BACKUP_CONFIG_FILE", "/data/config/config.json"))


def state_dir() -> Path:
    return Path(os.getenv("CLOUD_BACKUP_STATE_DIR", "/data/state"))


def log_dir() -> Path:
    return Path(os.getenv("CLOUD_BACKUP_LOG_DIR", "/data/logs"))


def rclone_config_path() -> Path:
    return Path(os.getenv("CLOUD_BACKUP_RCLONE_CONFIG", "/data/rclone/rclone.conf"))


def ensure_layout() -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    state_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    rclone_config_path().parent.mkdir(parents=True, exist_ok=True)


def _merge_defaults(defaults: dict[str, Any], persisted: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in persisted.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("Persisted config must be a JSON object")

    migrated = _merge_defaults(default_config(), config)
    if "schema_version" not in config:
        migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def load_config() -> dict[str, Any]:
    ensure_layout()
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg
    persisted = json.loads(path.read_text(encoding="utf-8"))
    data = migrate_config(persisted)
    data.setdefault("provider", {})
    data["provider"]["rclone_config"] = read_rclone_config()
    validate_config(data)
    if data != persisted:
        save_config(data)
    return data


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    ensure_layout()
    normalized = copy.deepcopy(config)
    validate_config(normalized)
    rclone_text = normalized.get("provider", {}).get("rclone_config", "")
    persisted = copy.deepcopy(normalized)
    if "provider" in persisted:
        persisted["provider"]["rclone_config"] = ""
    config_path().write_text(json.dumps(persisted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if rclone_text:
        rclone_config_path().write_text(rclone_text.strip() + "\n", encoding="utf-8")
    elif not rclone_config_path().exists():
        rclone_config_path().write_text("", encoding="utf-8")
    return normalized


def export_bundle(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "config": copy.deepcopy(config),
    }


def import_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported schema_version for import")
    config = bundle.get("config")
    if not isinstance(config, dict):
        raise ValueError("Import bundle is missing config")
    validate_config(config)
    return config


def coerce_import_config(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Import payload must be a JSON object")

    if isinstance(payload.get("bundle"), dict):
        return import_bundle(payload["bundle"])

    if isinstance(payload.get("config"), dict):
        config = payload["config"]
        validate_config(config)
        return config

    if "general" in payload and "provider" in payload and "sources" in payload:
        validate_config(payload)
        return payload

    raise ValueError("Import must contain either bundle, config, or a full config.json payload")


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")

    general = _require_dict(config, "general")
    provider = _require_dict(config, "provider")
    schedule = _require_dict(config, "schedule")
    retention = _require_dict(config, "retention")
    notifications = _require_dict(config, "notifications")
    security = _require_dict(config, "security")

    _require_non_empty_string(general, "instance_name")
    _require_list_of_strings(general, "authorized_roots")
    _require_non_empty_string(general, "restore_root")
    _require_positive_int(general, "log_retention_days")

    _require_non_empty_string(provider, "type")
    _require_non_empty_string(provider, "remote_name")
    _require_non_empty_string(provider, "repository")
    if provider.get("repository", "").startswith("rclone:"):
        if f"rclone:{provider['remote_name']}:" not in provider["repository"]:
            raise ValueError("provider.repository must reference provider.remote_name")
    _require_string(provider, "restic_password")
    _require_string(provider, "rclone_config")

    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("each source must be an object")
        _require_non_empty_string(source, "path")
        if not isinstance(source.get("enabled"), bool):
            raise ValueError("source.enabled must be boolean")
        if not isinstance(source.get("allow_empty"), bool):
            raise ValueError("source.allow_empty must be boolean")

    exclusions = config.get("exclusions")
    if not isinstance(exclusions, list):
        raise ValueError("exclusions must be a list")
    for pattern in exclusions:
        if not isinstance(pattern, str):
            raise ValueError("each exclusion must be a string")

    for job_name in ("backup", "forget", "prune"):
        job = _require_dict(schedule, job_name)
        if not isinstance(job.get("enabled"), bool):
            raise ValueError(f"schedule.{job_name}.enabled must be boolean")
        _require_non_empty_string(job, "time")
        _validate_time(job["time"], f"schedule.{job_name}.time")
        days = job.get("days_of_week")
        if not isinstance(days, list) or not all(isinstance(day, int) and 0 <= day <= 6 for day in days):
            raise ValueError(f"schedule.{job_name}.days_of_week must be a list of integers between 0 and 6")

    for field in ("keep_last", "keep_daily", "keep_weekly", "keep_monthly"):
        _require_positive_int(retention, field)

    for field in ("telegram_bot_token", "telegram_chat_id", "webhook_url"):
        _require_string(notifications, field)
    for field in ("notify_on_success", "notify_on_failure"):
        if not isinstance(notifications.get(field), bool):
            raise ValueError(f"notifications.{field} must be boolean")

    if not isinstance(security.get("require_remote_connectivity"), bool):
        raise ValueError("security.require_remote_connectivity must be boolean")
    if not isinstance(security.get("abort_on_unexpected_empty_source"), bool):
        raise ValueError("security.abort_on_unexpected_empty_source must be boolean")
    _require_list_of_strings(security, "expected_mounts")
    for field in ("disk_health_status_file", "disk_health_blocker_file", "mdstat_file"):
        _require_string(security, field)

    limits = _require_dict(config, "limits")
    _require_string(limits, "bandwidth_limit")
    threshold = limits.get("capacity_alert_threshold_percent")
    if not isinstance(threshold, int) or threshold < 1 or threshold > 100:
        raise ValueError("limits.capacity_alert_threshold_percent must be between 1 and 100")


def _require_dict(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _require_string(config: dict[str, Any], key: str) -> None:
    if not isinstance(config.get(key), str):
        raise ValueError(f"{key} must be a string")


def _require_non_empty_string(config: dict[str, Any], key: str) -> None:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")


def _require_list_of_strings(config: dict[str, Any], key: str) -> None:
    value = config.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{key} must be a non-empty list of strings")


def _require_positive_int(config: dict[str, Any], key: str) -> None:
    value = config.get(key)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")


def _validate_time(value: str, name: str) -> None:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"{name} must use HH:MM")
    hour, minute = parts
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError(f"{name} must use numeric HH:MM")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError(f"{name} is outside valid range")


def read_rclone_config() -> str:
    path = rclone_config_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
