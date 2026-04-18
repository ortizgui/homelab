from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT NOT NULL,
    internet_ok INTEGER NOT NULL,
    dns_ok INTEGER NOT NULL,
    offline INTEGER NOT NULL,
    details_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status, ts);

CREATE TABLE IF NOT EXISTS hourly_rollups (
    bucket TEXT PRIMARY KEY,
    total_samples INTEGER NOT NULL DEFAULT 0,
    issue_samples INTEGER NOT NULL DEFAULT 0,
    healthy INTEGER NOT NULL DEFAULT 0,
    dns_issue INTEGER NOT NULL DEFAULT 0,
    offline INTEGER NOT NULL DEFAULT 0,
    degraded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_rollups (
    bucket TEXT PRIMARY KEY,
    total_samples INTEGER NOT NULL DEFAULT 0,
    issue_samples INTEGER NOT NULL DEFAULT 0,
    healthy INTEGER NOT NULL DEFAULT 0,
    dns_issue INTEGER NOT NULL DEFAULT 0,
    offline INTEGER NOT NULL DEFAULT 0,
    degraded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_incident_rollups (
    bucket TEXT PRIMARY KEY,
    total_incidents INTEGER NOT NULL DEFAULT 0,
    dns_issue_incidents INTEGER NOT NULL DEFAULT 0,
    offline_incidents INTEGER NOT NULL DEFAULT 0,
    degraded_incidents INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metric_latency_rollups (
    bucket_type TEXT NOT NULL,
    bucket TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    metric_kind TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    latency_sum_ms REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_type, bucket, metric_key)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def insert_sample(self, sample: dict) -> None:
        status = sample["status"]
        payload_json = json.dumps(sample, separators=(",", ":"), sort_keys=True)
        hourly_bucket = sample["ts"][:13] + ":00:00+00:00"
        daily_bucket = sample["ts"][:10]
        counters = (
            int(status != "healthy"),
            int(status == "healthy"),
            int(status == "dns_issue"),
            int(status == "offline"),
            int(status == "degraded"),
        )
        metric_rows: list[tuple[str, str, str, str, str, int, int, float]] = []

        for item in sample["tcp_results"]:
            metric_rows.extend(
                self._build_metric_rollup_rows(
                    hourly_bucket=hourly_bucket,
                    daily_bucket=daily_bucket,
                    metric_key=f"tcp::{item['target']}",
                    metric_label=f"TCP {item['target']}",
                    metric_kind="tcp",
                    latency_ms=item.get("latency_ms"),
                    ok=item["ok"],
                )
            )

        for item in sample["dns_results"]:
            metric_rows.extend(
                self._build_metric_rollup_rows(
                    hourly_bucket=hourly_bucket,
                    daily_bucket=daily_bucket,
                    metric_key=f"dns::{item['resolver']}",
                    metric_label=f"DNS {item['resolver']}",
                    metric_kind="dns",
                    latency_ms=item.get("latency_ms"),
                    ok=item["ok"],
                )
            )

        with self.connect() as conn:
            previous = conn.execute(
                "SELECT status FROM samples ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            previous_status = previous["status"] if previous else None
            incident_started = status != "healthy" and status != previous_status

            conn.execute(
                """
                INSERT INTO samples (ts, status, internet_ok, dns_ok, offline, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sample["ts"],
                    status,
                    int(sample["internet_ok"]),
                    int(sample["dns_ok"]),
                    int(sample["offline"]),
                    payload_json,
                ),
            )
            conn.execute(
                """
                INSERT INTO hourly_rollups (
                    bucket, total_samples, issue_samples, healthy, dns_issue, offline, degraded
                ) VALUES (?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket) DO UPDATE SET
                    total_samples = total_samples + 1,
                    issue_samples = issue_samples + excluded.issue_samples,
                    healthy = healthy + excluded.healthy,
                    dns_issue = dns_issue + excluded.dns_issue,
                    offline = offline + excluded.offline,
                    degraded = degraded + excluded.degraded
                """,
                (hourly_bucket, *counters),
            )
            conn.execute(
                """
                INSERT INTO daily_rollups (
                    bucket, total_samples, issue_samples, healthy, dns_issue, offline, degraded
                ) VALUES (?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket) DO UPDATE SET
                    total_samples = total_samples + 1,
                    issue_samples = issue_samples + excluded.issue_samples,
                    healthy = healthy + excluded.healthy,
                    dns_issue = dns_issue + excluded.dns_issue,
                    offline = offline + excluded.offline,
                    degraded = degraded + excluded.degraded
                """,
                (daily_bucket, *counters),
            )
            if incident_started:
                conn.execute(
                    """
                    INSERT INTO daily_incident_rollups (
                        bucket, total_incidents, dns_issue_incidents, offline_incidents, degraded_incidents
                    ) VALUES (?, 1, ?, ?, ?)
                    ON CONFLICT(bucket) DO UPDATE SET
                        total_incidents = total_incidents + 1,
                        dns_issue_incidents = dns_issue_incidents + excluded.dns_issue_incidents,
                        offline_incidents = offline_incidents + excluded.offline_incidents,
                        degraded_incidents = degraded_incidents + excluded.degraded_incidents
                    """,
                    (
                        daily_bucket,
                        int(status == "dns_issue"),
                        int(status == "offline"),
                        int(status == "degraded"),
                    ),
                )
            if metric_rows:
                conn.executemany(
                    """
                    INSERT INTO metric_latency_rollups (
                        bucket_type, bucket, metric_key, metric_label, metric_kind,
                        success_count, failure_count, latency_sum_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bucket_type, bucket, metric_key) DO UPDATE SET
                        success_count = success_count + excluded.success_count,
                        failure_count = failure_count + excluded.failure_count,
                        latency_sum_ms = latency_sum_ms + excluded.latency_sum_ms,
                        metric_label = excluded.metric_label,
                        metric_kind = excluded.metric_kind
                    """,
                    metric_rows,
                )
            conn.commit()

    def _build_metric_rollup_rows(
        self,
        *,
        hourly_bucket: str,
        daily_bucket: str,
        metric_key: str,
        metric_label: str,
        metric_kind: str,
        latency_ms: float | None,
        ok: bool,
    ) -> list[tuple[str, str, str, str, str, int, int, float]]:
        success_count = int(ok)
        failure_count = int(not ok)
        latency_sum_ms = float(latency_ms or 0)
        return [
            (
                "hour",
                hourly_bucket,
                metric_key,
                metric_label,
                metric_kind,
                success_count,
                failure_count,
                latency_sum_ms,
            ),
            (
                "day",
                daily_bucket,
                metric_key,
                metric_label,
                metric_kind,
                success_count,
                failure_count,
                latency_sum_ms,
            ),
        ]

    def prune_old_samples(self, retention_days: int) -> int:
        threshold = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM samples WHERE ts < ?", (threshold,))
            conn.commit()
            return cursor.rowcount

    def prune_samples_by_size(self, max_size_mb: int) -> int:
        max_bytes = max_size_mb * 1024 * 1024
        deleted = 0
        with self.connect() as conn:
            while True:
                current_bytes = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(details_json)), 0) AS total FROM samples"
                ).fetchone()["total"]
                if current_bytes <= max_bytes:
                    break

                ids = conn.execute(
                    "SELECT id FROM samples ORDER BY ts ASC LIMIT 500"
                ).fetchall()
                if not ids:
                    break

                conn.executemany("DELETE FROM samples WHERE id = ?", [(row["id"],) for row in ids])
                deleted += len(ids)

            conn.commit()
        return deleted

    def prune_rollups(self, retention_days: int) -> int:
        threshold_dt = datetime.now(UTC) - timedelta(days=retention_days)
        hourly_threshold = threshold_dt.strftime("%Y-%m-%dT%H:00:00+00:00")
        daily_threshold = threshold_dt.strftime("%Y-%m-%d")
        with self.connect() as conn:
            hourly_deleted = conn.execute(
                "DELETE FROM hourly_rollups WHERE bucket < ?",
                (hourly_threshold,),
            ).rowcount
            daily_deleted = conn.execute(
                "DELETE FROM daily_rollups WHERE bucket < ?",
                (daily_threshold,),
            ).rowcount
            incident_deleted = conn.execute(
                "DELETE FROM daily_incident_rollups WHERE bucket < ?",
                (daily_threshold,),
            ).rowcount
            metric_deleted = conn.execute(
                """
                DELETE FROM metric_latency_rollups
                WHERE (bucket_type = 'hour' AND bucket < ?)
                   OR (bucket_type = 'day' AND bucket < ?)
                """,
                (hourly_threshold, daily_threshold),
            ).rowcount
            conn.commit()
        return hourly_deleted + daily_deleted + incident_deleted + metric_deleted

    def fetch_recent_samples(self, hours: int = 24 * 30) -> list[sqlite3.Row]:
        threshold = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT ts, status, details_json FROM samples WHERE ts >= ? ORDER BY ts ASC",
                (threshold,),
            ).fetchall()
        return rows

    def fetch_status_counts_last_24h(self) -> list[sqlite3.Row]:
        threshold = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM samples
                WHERE ts >= ?
                GROUP BY status
                ORDER BY total DESC
                """,
                (threshold,),
            ).fetchall()
        return rows

    def fetch_hourly_rollups(self, limit: int = 24) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT bucket, issue_samples, total_samples, healthy, dns_issue, offline, degraded
                FROM hourly_rollups
                ORDER BY bucket DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(reversed(rows))

    def fetch_daily_rollups(self, limit: int = 180) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT bucket, issue_samples, total_samples, healthy, dns_issue, offline, degraded
                FROM daily_rollups
                ORDER BY bucket DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(reversed(rows))

    def fetch_incident_totals(self, days: int) -> dict[str, int]:
        threshold = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(total_incidents), 0) AS total_incidents,
                    COALESCE(SUM(dns_issue_incidents), 0) AS dns_issue_incidents,
                    COALESCE(SUM(offline_incidents), 0) AS offline_incidents,
                    COALESCE(SUM(degraded_incidents), 0) AS degraded_incidents
                FROM daily_incident_rollups
                WHERE bucket >= ?
                """,
                (threshold,),
            ).fetchone()
        return {
            "days": days,
            "total": int(row["total_incidents"]),
            "dns_issue": int(row["dns_issue_incidents"]),
            "offline": int(row["offline_incidents"]),
            "degraded": int(row["degraded_incidents"]),
        }

    def fetch_metric_latency_rollups(self, bucket_type: str, limit: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    bucket_type,
                    bucket,
                    metric_key,
                    metric_label,
                    metric_kind,
                    success_count,
                    failure_count,
                    latency_sum_ms
                FROM metric_latency_rollups
                WHERE bucket_type = ?
                ORDER BY bucket DESC, metric_key ASC
                """,
                (bucket_type,),
            ).fetchall()

        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["bucket"], []).append(row)

        selected_buckets = sorted(grouped.keys())[-limit:]
        flattened: list[sqlite3.Row] = []
        for bucket in selected_buckets:
            flattened.extend(grouped[bucket])
        return flattened

    def get_runtime_settings(self, defaults: dict[str, int]) -> dict[str, int]:
        settings = defaults.copy()
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        for row in rows:
            if row["key"] in settings:
                settings[row["key"]] = int(row["value"])
        return settings

    def update_runtime_settings(self, values: dict[str, int]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [(key, str(value), now) for key, value in values.items()],
            )
            conn.commit()

    def fetch_sample_storage_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS sample_count,
                       COALESCE(SUM(LENGTH(details_json)), 0) AS sample_bytes
                FROM samples
                """
            ).fetchone()
        return {
            "sample_count": int(row["sample_count"]),
            "sample_bytes": int(row["sample_bytes"]),
        }

    def fetch_latest_sample(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT ts, status, details_json FROM samples ORDER BY ts DESC LIMIT 1"
            ).fetchone()
