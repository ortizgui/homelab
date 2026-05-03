# Decision: Netpulse Monitoring Approach

## Context
Lightweight connectivity monitor that distinguishes between internet outages and DNS failures, with historical data visualization and configurable retention.

## Decision
- **Dual-dimension probing**: TCP connect (port 53) to public resolvers for IP connectivity + DNS A-record query to same resolvers for DNS resolution
- **Status classification**: healthy, dns_issue (IP works, DNS fails), offline (both fail), degraded (asymmetric behavior)
- **SQLite with tiered storage**: Raw samples (short retention, by age+size), hourly/daily rollups (long retention for charts), metric latency rollups (per-probe latency history)
- **Background thread**: MonitorThread polls on configurable interval (default 30s), runs in background daemon thread
- **Flask web server**: Same process serves API + renders Jinja2 template dashboard
- **Runtime settings**: Retention config stored in SQLite `app_settings` table, editable via UI
- **Chart rendering**: Purely client-side SVG (no charting library)

## Rationale
- TCP connect instead of ping avoids ICMP filtering/prioritization issues
- Separating TCP and DNS probes enables root cause analysis (network vs resolver)
- Rollup tables keep historical charts performant without storing all raw samples forever
- Dual retention (age + size) prevents unbounded log growth
- Same-process design (Flask + monitor thread) keeps deployment simple (single container)
- Client-side SVG avoids JavaScript chart library dependency

## Alternatives Considered
- **ICMP ping only**: Cannot distinguish network vs DNS issues
- **External monitoring service (UptimeRobot, etc.)**: Cannot monitor internal connectivity
- **Prometheus + node_exporter**: Overkill; Netpulse is purpose-built
- **Separate worker process**: Adds complexity; threading is sufficient

## Related
- [Project Intent](../intent/project-intent.md)
- [Feature: Network Connectivity Monitoring](../intent/feature-netpulse.md)
- [Pattern: SQLite Rollup Tables](../knowledge/patterns/sqlite-rollup-tables.md)
- [Decision: Tech Stack](../decisions/001-tech-stack.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Accepted
