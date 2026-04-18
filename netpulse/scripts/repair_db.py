#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

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


def build_metric_rows(
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


def rebuild_aggregates(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        sample_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='samples'"
        ).fetchone()
        if not sample_exists:
            print("Tabela 'samples' não existe. Nada para reconstruir.")
            return

        samples = conn.execute(
            "SELECT ts, status, details_json FROM samples ORDER BY ts ASC"
        ).fetchall()
        print(f"Encontradas {len(samples)} amostras para reprocessar.")

        conn.execute("DELETE FROM hourly_rollups")
        conn.execute("DELETE FROM daily_rollups")
        conn.execute("DELETE FROM daily_incident_rollups")
        conn.execute("DELETE FROM metric_latency_rollups")

        previous_status: str | None = None
        for row in samples:
            payload = json.loads(row["details_json"])
            status = payload["status"]
            hourly_bucket = payload["ts"][:13] + ":00:00+00:00"
            daily_bucket = payload["ts"][:10]
            counters = (
                int(status != "healthy"),
                int(status == "healthy"),
                int(status == "dns_issue"),
                int(status == "offline"),
                int(status == "degraded"),
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

            if status != "healthy" and status != previous_status:
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

            metric_rows: list[tuple[str, str, str, str, str, int, int, float]] = []
            for item in payload.get("tcp_results", []):
                metric_rows.extend(
                    build_metric_rows(
                        hourly_bucket=hourly_bucket,
                        daily_bucket=daily_bucket,
                        metric_key=f"tcp::{item['target']}",
                        metric_label=f"TCP {item['target']}",
                        metric_kind="tcp",
                        latency_ms=item.get("latency_ms"),
                        ok=item.get("ok", False),
                    )
                )
            for item in payload.get("dns_results", []):
                metric_rows.extend(
                    build_metric_rows(
                        hourly_bucket=hourly_bucket,
                        daily_bucket=daily_bucket,
                        metric_key=f"dns::{item['resolver']}",
                        metric_label=f"DNS {item['resolver']}",
                        metric_kind="dns",
                        latency_ms=item.get("latency_ms"),
                        ok=item.get("ok", False),
                    )
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

            previous_status = status

        conn.commit()

        sample_count = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        metric_count = conn.execute("SELECT COUNT(*) FROM metric_latency_rollups").fetchone()[0]
        print(f"Rebuild concluído. samples={sample_count} metric_latency_rollups={metric_count}")
    finally:
        conn.close()


def load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_db_path() -> str:
    env_values = load_env_file(ROOT_DIR / ".env")
    env_db_path = os.getenv("NETPULSE_DB_PATH") or env_values.get("NETPULSE_DB_PATH")
    if env_db_path:
        return env_db_path

    data_dir = os.getenv("NETPULSE_DATA_DIR") or env_values.get("NETPULSE_DATA_DIR")
    if data_dir:
        data_path = Path(data_dir)
        if not data_path.is_absolute():
          data_path = ROOT_DIR / data_path
        return str(data_path / "netpulse.sqlite3")

    container_default = Path("/data/netpulse.sqlite3")
    if container_default.parent.exists():
        return str(container_default)
    return str(ROOT_DIR / "data" / "netpulse.sqlite3")


def main() -> None:
    db_path = resolve_db_path()
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        db_file.touch()
    print(f"Usando banco em: {db_file}")
    rebuild_aggregates(str(db_file))


if __name__ == "__main__":
    main()
