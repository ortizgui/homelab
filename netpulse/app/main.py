from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
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


def _build_daily_events(samples: list[dict], poll_interval: int) -> dict[str, list[dict]]:
    events_by_day: dict[str, list[dict]] = {}
    max_gap = poll_interval * 2.5

    for sample in samples:
        if sample["status"] == "healthy":
            continue
        local_dt = datetime.fromisoformat(sample["ts"]).astimezone(ZoneInfo(SETTINGS.timezone))
        day_key = local_dt.strftime("%Y-%m-%d")
        events_by_day.setdefault(day_key, []).append(sample)

    result: dict[str, list[dict]] = {}

    for day_key, day_samples in events_by_day.items():
        day_samples.sort(key=lambda s: s["ts"])
        events: list[dict] = []
        current: dict | None = None

        def _nearest_event():
            current["duration_seconds"] = max(
                0,
                int(
                    (
                        datetime.fromisoformat(current["ended_at"])
                        - datetime.fromisoformat(current["started_at"])
                    ).total_seconds()
                ),
            )
            if current["duration_seconds"] == 0 and current["total"] > 0:
                current["duration_seconds"] = poll_interval
                start_dt = datetime.fromisoformat(current["started_at"])
                estimated_end = start_dt + timedelta(seconds=poll_interval)
                current["ended_at"] = estimated_end.isoformat()
                current["ended_at_local"] = estimated_end.astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%H:%M:%S")
            return current

        for sample in day_samples:
            local_dt = datetime.fromisoformat(sample["ts"]).astimezone(ZoneInfo(SETTINGS.timezone))
            local_str = local_dt.strftime("%H:%M:%S")
            if current is None:
                current = {
                    "started_at": sample["ts"],
                    "started_at_local": local_str,
                    "ended_at": sample["ts"],
                    "ended_at_local": local_str,
                    "offline": 0,
                    "dns_issue": 0,
                    "degraded": 0,
                    "total": 0,
                }
            else:
                prev_dt = datetime.fromisoformat(current["ended_at"]).astimezone(ZoneInfo(SETTINGS.timezone))
                gap = (local_dt - prev_dt).total_seconds()
                if gap > max_gap:
                    events.append(_nearest_event())
                    current = {
                        "started_at": sample["ts"],
                        "started_at_local": local_str,
                        "ended_at": sample["ts"],
                        "ended_at_local": local_str,
                        "offline": 0,
                        "dns_issue": 0,
                        "degraded": 0,
                        "total": 0,
                    }
                else:
                    current["ended_at"] = sample["ts"]
                    current["ended_at_local"] = local_str
            current["offline"] += int(sample["status"] == "offline")
            current["dns_issue"] += int(sample["status"] == "dns_issue")
            current["degraded"] += int(sample["status"] == "degraded")
            current["total"] += 1

        if current is not None:
            events.append(_nearest_event())

        result[day_key] = events

    return result


def _build_chart_series(
    samples: list[dict], graph_retention_days: int, poll_interval: int
) -> tuple[list[dict], list[dict], list[dict]]:
    hourly_rows = STORAGE.fetch_hourly_rollups(limit=24)
    daily_rows = STORAGE.fetch_daily_rollups(limit=graph_retention_days)
    detail_hourly_rows = STORAGE.fetch_hourly_rollups(limit=graph_retention_days * 24)
    events_by_day = _build_daily_events(samples, poll_interval)
    daily_groups: dict[str, dict] = {}
    daily_order: list[str] = []
    for row in detail_hourly_rows:
        local_bucket = datetime.fromisoformat(row["bucket"]).astimezone(ZoneInfo(SETTINGS.timezone))
        day_key = local_bucket.strftime("%Y-%m-%d")
        if day_key not in daily_groups:
            daily_order.append(day_key)
            daily_groups[day_key] = {
                "date": day_key,
                "bucket": local_bucket.strftime("%m-%d"),
                "count": 0,
                "offline": 0,
                "dns_issue": 0,
                "degraded": 0,
                "hours": [],
                "events": [],
            }
        day = daily_groups[day_key]
        day["count"] += row["issue_samples"]
        day["offline"] += row["offline"]
        day["dns_issue"] += row["dns_issue"]
        day["degraded"] += row["degraded"]
        day["events"] = events_by_day.get(day_key, [])
        if row["issue_samples"]:
            day["hours"].append(
                {
                    "bucket": local_bucket.strftime("%m-%d %H:00"),
                    "count": row["issue_samples"],
                    "offline": row["offline"],
                    "dns_issue": row["dns_issue"],
                    "degraded": row["degraded"],
                }
            )
    hourly_series = [
        {
            "bucket": datetime.fromisoformat(row["bucket"]).astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%m-%d %H:00"),
            "count": row["issue_samples"],
            "offline": row["offline"],
            "dns_issue": row["dns_issue"],
            "degraded": row["degraded"],
        }
        for row in hourly_rows
    ]
    daily_series = [daily_groups[day_key] for day_key in daily_order] or [
        {
            "date": row["bucket"],
            "bucket": row["bucket"][5:],
            "count": row["issue_samples"],
            "offline": row["offline"],
            "dns_issue": row["dns_issue"],
            "degraded": row["degraded"],
            "hours": [],
            "events": events_by_day.get(row["bucket"], []),
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


def _bucket_sample_ts(ts: str, minutes: int = 5) -> datetime:
    local_dt = datetime.fromisoformat(ts).astimezone(ZoneInfo(SETTINGS.timezone))
    minute = (local_dt.minute // minutes) * minutes
    return local_dt.replace(minute=minute, second=0, microsecond=0)


def _build_featured_short_windows(samples: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for window_name, hours in (("12h", 12), ("24h", 24)):
        scoped = samples[-hours * 12 :]
        buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"offline": 0, "dns_issue": 0, "degraded": 0, "total": 0}
        )
        order: list[str] = []
        for sample in scoped:
            bucket_dt = _bucket_sample_ts(sample["ts"], 5)
            bucket_key = bucket_dt.isoformat()
            if bucket_key not in buckets:
                order.append(bucket_key)
            if sample["status"] != "healthy":
                buckets[bucket_key][sample["status"]] += 1
                buckets[bucket_key]["total"] += 1

        result[window_name] = [
            {
                "bucket": datetime.fromisoformat(bucket_key).strftime("%m-%d %H:%M"),
                "offline": buckets[bucket_key]["offline"],
                "dns_issue": buckets[bucket_key]["dns_issue"],
                "degraded": buckets[bucket_key]["degraded"],
                "total": buckets[bucket_key]["total"],
            }
            for bucket_key in order
        ]
    return result


def _build_featured_breakdown_windows(graph_retention_days: int, samples: list[dict]) -> dict[str, list[dict]]:
    hourly_rows = STORAGE.fetch_hourly_rollups(limit=24)
    daily_rows = STORAGE.fetch_daily_rollups(limit=graph_retention_days)
    windows = {
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
    windows.update(_build_featured_short_windows(samples))
    return windows


def _build_latency_short_windows(samples: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for window_name, hours in (("12h", 12), ("24h", 24)):
        scoped = samples[-hours * 12 :]
        bucket_metric_acc: dict[str, dict[str, dict[str, float | int | str]]] = defaultdict(dict)
        bucket_order: list[str] = []

        for sample in scoped:
            bucket_dt = _bucket_sample_ts(sample["ts"], 5)
            bucket_key = bucket_dt.isoformat()
            if bucket_key not in bucket_metric_acc:
                bucket_order.append(bucket_key)

            for item in sample["tcp_results"]:
                metric_key = f"tcp::{item['target']}"
                entry = bucket_metric_acc[bucket_key].setdefault(
                    metric_key,
                    {
                        "label": f"TCP {item['target']}",
                        "kind": "tcp",
                        "success_count": 0,
                        "failure_count": 0,
                        "latency_sum_ms": 0.0,
                    },
                )
                if item["ok"]:
                    entry["success_count"] += 1
                    entry["latency_sum_ms"] += float(item.get("latency_ms") or 0)
                else:
                    entry["failure_count"] += 1

            for item in sample["dns_results"]:
                metric_key = f"dns::{item['resolver']}"
                entry = bucket_metric_acc[bucket_key].setdefault(
                    metric_key,
                    {
                        "label": f"DNS {item['resolver']}",
                        "kind": "dns",
                        "success_count": 0,
                        "failure_count": 0,
                        "latency_sum_ms": 0.0,
                    },
                )
                if item["ok"]:
                    entry["success_count"] += 1
                    entry["latency_sum_ms"] += float(item.get("latency_ms") or 0)
                else:
                    entry["failure_count"] += 1

        metric_keys = sorted({key for bucket in bucket_metric_acc.values() for key in bucket.keys()})
        metric_meta = {
            key: next(bucket[key] for bucket in bucket_metric_acc.values() if key in bucket)
            for key in metric_keys
        }
        series = [
            {"key": key, "label": metric_meta[key]["label"], "kind": metric_meta[key]["kind"], "values": []}
            for key in metric_keys
        ]
        timeline: list[dict] = []
        for bucket_key in bucket_order:
            metrics = []
            for series_item in series:
                entry = bucket_metric_acc[bucket_key].get(series_item["key"])
                if entry and entry["success_count"]:
                    avg_latency = round(entry["latency_sum_ms"] / entry["success_count"], 1)
                else:
                    avg_latency = None
                failure_count = int(entry["failure_count"]) if entry else 0
                series_item["values"].append(avg_latency)
                metrics.append(
                    {
                        "label": series_item["label"],
                        "value": avg_latency,
                        "ok": avg_latency is not None,
                        "failures": failure_count,
                    }
                )
            timeline.append(
                {
                    "bucket": datetime.fromisoformat(bucket_key).strftime("%m-%d %H:%M"),
                    "metrics": metrics,
                }
            )
        result[window_name] = {"series": series, "timeline": timeline}
    return result


def _build_latency_series(graph_retention_days: int, samples: list[dict]) -> dict[str, dict]:
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
    result = {
        "7d": build_payload(trim_bucket_rows(daily_rows, 7), "day"),
        "30d": build_payload(trim_bucket_rows(daily_rows, 30), "day"),
        "90d": build_payload(trim_bucket_rows(daily_rows, 90), "day"),
        "180d": build_payload(trim_bucket_rows(daily_rows, 180), "day"),
        "365d": build_payload(trim_bucket_rows(daily_rows, 365), "day"),
    }
    result.update(_build_latency_short_windows(samples))
    return result


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
    hourly_series, daily_series, _ = _build_chart_series(samples, runtime["graph_retention_days"], SETTINGS.poll_interval_seconds)
    featured_windows = _build_featured_breakdown_windows(runtime["graph_retention_days"], samples)
    latency_series = _build_latency_series(runtime["graph_retention_days"], samples)
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
