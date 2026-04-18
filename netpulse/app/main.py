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


def _build_featured_breakdown_windows(graph_retention_days: int) -> dict[str, list[dict]]:
    hourly_rows = STORAGE.fetch_hourly_rollups(limit=24)
    daily_rows = STORAGE.fetch_daily_rollups(limit=graph_retention_days)
    return {
        "12h": [
            {
                "bucket": datetime.fromisoformat(row["bucket"]).astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%m-%d %H:00"),
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in hourly_rows[-12:]
        ],
        "24h": [
            {
                "bucket": datetime.fromisoformat(row["bucket"]).astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%m-%d %H:00"),
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in hourly_rows
        ],
        "7d": [
            {
                "bucket": row["bucket"][5:],
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in daily_rows[-7:]
        ],
        "30d": [
            {
                "bucket": row["bucket"][5:],
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in daily_rows[-30:]
        ],
        "90d": [
            {
                "bucket": row["bucket"][5:],
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in daily_rows[-90:]
        ],
        "180d": [
            {
                "bucket": row["bucket"][5:],
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in daily_rows[-180:]
        ],
        "365d": [
            {
                "bucket": row["bucket"][5:],
                "offline": row["offline"],
                "dns_issue": row["dns_issue"],
                "degraded": row["degraded"],
                "total": row["issue_samples"],
            }
            for row in daily_rows[-365:]
        ],
    }


def _build_latency_series(graph_retention_days: int) -> dict[str, dict]:
    def group_rows_by_bucket(rows: list) -> list[list]:
        grouped: dict[str, list] = {}
        for row in rows:
            grouped.setdefault(row["bucket"], []).append(row)
        return [grouped[bucket] for bucket in sorted(grouped.keys())]

    def trim_bucket_rows(rows: list, bucket_limit: int) -> list:
        grouped_rows = group_rows_by_bucket(rows)
        trimmed = grouped_rows[-bucket_limit:]
        return [row for bucket_rows in trimmed for row in bucket_rows]

    def build_payload(rows: list, bucket_type: str) -> dict:
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for row in rows:
            bucket = row["bucket"]
            metric_key = row["metric_key"]
            if bucket not in grouped:
                grouped[bucket] = {"bucket": bucket, "metrics": {}, "order": []}
                order.append(bucket)
            if metric_key not in grouped[bucket]["metrics"]:
                grouped[bucket]["metrics"][metric_key] = row
                grouped[bucket]["order"].append(metric_key)

        series_index: dict[str, dict] = {}
        for row in rows:
            metric_key = row["metric_key"]
            if metric_key not in series_index:
                series_index[metric_key] = {
                    "key": metric_key,
                    "label": row["metric_label"],
                    "kind": row["metric_kind"],
                    "values": [],
                }

        timeline: list[dict] = []
        for bucket in order:
            point = grouped[bucket]
            label = (
                datetime.fromisoformat(bucket).astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%m-%d %H:00")
                if bucket_type == "hour"
                else bucket[5:]
            )
            metrics = []
            for metric_key, meta in series_index.items():
                row = point["metrics"].get(metric_key)
                if row:
                    success_count = row["success_count"]
                    avg_latency = round(row["latency_sum_ms"] / success_count, 1) if success_count else None
                    failure_count = row["failure_count"]
                else:
                    avg_latency = None
                    failure_count = 0
                meta["values"].append(avg_latency)
                metrics.append(
                    {
                        "label": meta["label"],
                        "value": avg_latency,
                        "ok": avg_latency is not None,
                        "failures": int(failure_count),
                    }
                )
            timeline.append({"bucket": label, "metrics": metrics})

        return {"series": list(series_index.values()), "timeline": timeline}

    hourly_rows = STORAGE.fetch_metric_latency_rollups("hour", 24)
    daily_rows = STORAGE.fetch_metric_latency_rollups("day", graph_retention_days)
    return {
        "12h": build_payload(trim_bucket_rows(hourly_rows, 12), "hour"),
        "24h": build_payload(hourly_rows, "hour"),
        "7d": build_payload(trim_bucket_rows(daily_rows, 7), "day"),
        "30d": build_payload(trim_bucket_rows(daily_rows, 30), "day"),
        "90d": build_payload(trim_bucket_rows(daily_rows, 90), "day"),
        "180d": build_payload(trim_bucket_rows(daily_rows, 180), "day"),
        "365d": build_payload(trim_bucket_rows(daily_rows, 365), "day"),
    }


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
    hourly_series, daily_series, _ = _build_chart_series(runtime["graph_retention_days"])
    featured_windows = _build_featured_breakdown_windows(runtime["graph_retention_days"])
    latency_series = _build_latency_series(runtime["graph_retention_days"])
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
            "featured_windows": featured_windows,
            "latency_series": latency_series,
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
