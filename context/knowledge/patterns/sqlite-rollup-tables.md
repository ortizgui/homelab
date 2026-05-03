# Pattern: SQLite Rollup Tables

## Description
Pre-aggregated time-series tables that store summarized data at different granularities (hourly, daily) alongside raw samples. Enables long-term historical charts without storing all raw data indefinitely.

## When to Use
- Time-series data that needs both detailed recent view and long-term trends
- When storage is constrained but historical queries must be fast
- When raw data can be discarded after aggregation

## Pattern

```sql
-- Raw samples: detailed, short retention
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL
);

-- Hourly rollups: pre-aggregated by hour
CREATE TABLE hourly_rollups (
    bucket TEXT PRIMARY KEY,       -- "2025-12-01T13:00:00+00:00"
    total_samples INTEGER NOT NULL,
    issue_samples INTEGER NOT NULL,
    healthy INTEGER NOT NULL,
    dns_issue INTEGER NOT NULL,
    offline INTEGER NOT NULL,
    degraded INTEGER NOT NULL
);

-- Daily rollups: pre-aggregated by day
CREATE TABLE daily_rollups (
    bucket TEXT PRIMARY KEY,       -- "2025-12-01"
    total_samples INTEGER NOT NULL,
    issue_samples INTEGER NOT NULL,
    healthy INTEGER NOT NULL,
    dns_issue INTEGER NOT NULL,
    offline INTEGER NOT NULL,
    degraded INTEGER NOT NULL
);
```

## Example

From `netpulse/app/storage.py`:
```python
# On each sample insert, update rollups atomically
conn.execute("""
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
""", (hourly_bucket, *counters))

# Prune rollups by retention
def prune_rollups(self, retention_days: int) -> int:
    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    conn.execute("DELETE FROM hourly_rollups WHERE bucket < ?", (threshold,))
```

## Files Using This Pattern
- `netpulse/app/storage.py` - Full rollup implementation with hourly/daily/metric tables
- `netpulse/scripts/repair_db.py` - Rebuilds rollups from raw samples
- `netpulse/app/main.py` - Fetches from rollups for chart data (hourly_series, daily_series)

## Related
- [Decision: Netpulse Monitoring Approach](../decisions/003-netpulse-monitoring-approach.md)
- [Feature: Network Connectivity Monitoring](../intent/feature-netpulse.md)

## Status
- **Created**: 2026-05-03
- **Status**: Active
