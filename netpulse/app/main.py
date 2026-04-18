from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request

from .config import load_settings
from .monitor import MonitorThread
from .storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

SETTINGS = load_settings()
STORAGE = Storage(SETTINGS.db_path)
MONITOR = MonitorThread(SETTINGS, STORAGE)
RUNTIME_DEFAULTS = {
    "log_retention_days": SETTINGS.log_retention_days,
    "log_max_size_mb": SETTINGS.log_max_size_mb,
    "graph_retention_days": SETTINGS.graph_retention_days,
}

app = Flask(__name__, template_folder="../templates", static_folder="../static")


def _parse_row(row) -> dict | None:
    if not row:
        return None
    payload = json.loads(row["details_json"])
    payload["ts_local"] = _format_local(payload["ts"])
    return payload


def _format_local(ts: str) -> str:
    dt = datetime.fromisoformat(ts)
    local_dt = dt.astimezone(ZoneInfo(SETTINGS.timezone))
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _build_incidents(samples: list[dict]) -> list[dict]:
    incidents: list[dict] = []
    current: dict | None = None
    previous_ts: str | None = None

    for sample in samples:
        status = sample["status"]
        if status == "healthy":
            if current is not None:
                current["ended_at"] = sample["ts"]
                current["ended_at_local"] = _format_local(sample["ts"])
                incidents.append(current)
                current = None
            previous_ts = sample["ts"]
            continue

        if current is None:
            current = {
                "status": status,
                "started_at": sample["ts"],
                "started_at_local": _format_local(sample["ts"]),
                "ended_at": None,
                "ended_at_local": None,
                "samples": 1,
            }
        elif current["status"] == status:
            current["samples"] += 1
        else:
            current["ended_at"] = previous_ts or sample["ts"]
            current["ended_at_local"] = _format_local(current["ended_at"])
            incidents.append(current)
            current = {
                "status": status,
                "started_at": sample["ts"],
                "started_at_local": _format_local(sample["ts"]),
                "ended_at": None,
                "ended_at_local": None,
                "samples": 1,
            }

        previous_ts = sample["ts"]

    if current is not None and previous_ts is not None:
        current["ended_at"] = previous_ts
        current["ended_at_local"] = _format_local(previous_ts)
        incidents.append(current)

    for incident in incidents:
        start = datetime.fromisoformat(incident["started_at"])
        end = datetime.fromisoformat(incident["ended_at"])
        incident["duration_seconds"] = max(0, int((end - start).total_seconds()))

    return list(reversed(incidents[-20:]))


def _build_chart_series(graph_retention_days: int) -> tuple[list[dict], list[dict], list[dict]]:
    hourly_rows = STORAGE.fetch_hourly_rollups(limit=24)
    daily_rows = STORAGE.fetch_daily_rollups(limit=graph_retention_days)
    hourly_series = [
        {
            "bucket": datetime.fromisoformat(row["bucket"]).astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%m-%d %H:00"),
            "count": row["issue_samples"],
        }
        for row in hourly_rows
    ]
    daily_series = [
        {
            "bucket": row["bucket"][5:],
            "count": row["issue_samples"],
        }
        for row in daily_rows
    ]
    featured_series = [
        {
            "bucket": row["bucket"][5:],
            "offline": row["offline"],
            "dns_issue": row["dns_issue"],
            "degraded": row["degraded"],
            "total": row["issue_samples"],
        }
        for row in daily_rows
    ]
    return hourly_series, daily_series, featured_series


@app.get("/")
def index():
    runtime = STORAGE.get_runtime_settings(RUNTIME_DEFAULTS)
    return render_template(
        "index.html",
        poll_interval=SETTINGS.poll_interval_seconds,
        timezone=SETTINGS.timezone,
        runtime=runtime,
    )


@app.get("/api/summary")
def api_summary():
    raw_samples = STORAGE.fetch_recent_samples()
    samples = [json.loads(row["details_json"]) for row in raw_samples]
    latest = _parse_row(STORAGE.fetch_latest_sample())
    runtime = STORAGE.get_runtime_settings(RUNTIME_DEFAULTS)
    status_counts = [
        {"status": row["status"], "total": row["total"]}
        for row in STORAGE.fetch_status_counts_last_24h()
    ]
    incidents = _build_incidents(samples)
    hourly_series, daily_series, featured_series = _build_chart_series(runtime["graph_retention_days"])
    storage_stats = STORAGE.fetch_sample_storage_stats()
    incident_windows = [
        STORAGE.fetch_incident_totals(30),
        STORAGE.fetch_incident_totals(runtime["graph_retention_days"]),
    ]
    return jsonify(
        {
            "latest": latest,
            "status_counts_24h": status_counts,
            "incidents": incidents,
            "hourly_issues": hourly_series,
            "daily_issues": daily_series,
            "featured_daily_breakdown": featured_series,
            "incident_windows": incident_windows,
            "settings": runtime,
            "storage": storage_stats,
        }
    )


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    values = {
        "log_retention_days": max(1, int(payload.get("log_retention_days", RUNTIME_DEFAULTS["log_retention_days"]))),
        "log_max_size_mb": max(10, int(payload.get("log_max_size_mb", RUNTIME_DEFAULTS["log_max_size_mb"]))),
        "graph_retention_days": max(7, int(payload.get("graph_retention_days", RUNTIME_DEFAULTS["graph_retention_days"]))),
    }
    STORAGE.update_runtime_settings(values)
    STORAGE.prune_old_samples(values["log_retention_days"])
    STORAGE.prune_samples_by_size(values["log_max_size_mb"])
    STORAGE.prune_rollups(values["graph_retention_days"])
    return jsonify({"ok": True, "settings": STORAGE.get_runtime_settings(RUNTIME_DEFAULTS)})


def create_app() -> Flask:
    return app


if not MONITOR.is_alive():
    MONITOR.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
