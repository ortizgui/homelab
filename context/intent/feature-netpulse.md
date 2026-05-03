# Feature: Network Connectivity Monitoring (Netpulse)

## What
Lightweight internet connectivity monitor that periodically tests TCP connectivity and DNS resolution against public targets, classifies the connection state, and displays a web dashboard with historical charts and incident tracking.

## Why
Differentiate between internet outages and DNS failures to speed up troubleshooting. Provide historical visibility into connectivity quality, latency trends, and incident patterns over time.

## Acceptance Criteria
- [ ] Periodically probes TCP targets (default: 1.1.1.1:53, 8.8.8.8:53)
- [ ] Periodically resolves DNS hostname against multiple resolvers
- [ ] Classifies each sample as healthy, dns_issue, offline, or degraded
- [ ] Persists samples in SQLite with intelligent retention (raw logs + aggregated rollups)
- [ ] Web dashboard shows current status, recent incidents, hourly/daily heatmaps, and latency charts
- [ ] Retention policies for logs (by age and size) and graphs (aggregated) configurable via UI
- [ ] Low resource usage for 24x7 operation

## Related
- [Decision: Tech Stack](../decisions/001-tech-stack.md)
- [Decision: Netpulse Monitoring Approach](../decisions/003-netpulse-monitoring-approach.md)
- [Pattern: SQLite Rollup Tables](../knowledge/patterns/sqlite-rollup-tables.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Active (already implemented)
