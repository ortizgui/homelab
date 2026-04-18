from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_targets(value: str) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    for item in _parse_csv(value):
        host, _, port = item.partition(":")
        targets.append((host.strip(), int(port or "53")))
    return targets


@dataclass(frozen=True)
class Settings:
    timezone: str
    db_path: str
    poll_interval_seconds: int
    log_retention_days: int
    log_max_size_mb: int
    graph_retention_days: int
    dns_timeout_seconds: float
    tcp_timeout_seconds: float
    dns_hostname: str
    dns_resolvers: list[str]
    tcp_targets: list[tuple[str, int]]


def load_settings() -> Settings:
    return Settings(
        timezone=os.getenv("TZ", "America/Sao_Paulo"),
        db_path=os.getenv("NETPULSE_DB_PATH", "/data/netpulse.sqlite3"),
        poll_interval_seconds=max(5, int(os.getenv("NETPULSE_POLL_INTERVAL_SECONDS", "30"))),
        log_retention_days=max(
            1,
            int(
                os.getenv(
                    "NETPULSE_LOG_RETENTION_DAYS",
                    os.getenv("NETPULSE_RETENTION_DAYS", "30"),
                )
            ),
        ),
        log_max_size_mb=max(10, int(os.getenv("NETPULSE_LOG_MAX_SIZE_MB", "100"))),
        graph_retention_days=max(7, int(os.getenv("NETPULSE_GRAPH_RETENTION_DAYS", "180"))),
        dns_timeout_seconds=float(os.getenv("NETPULSE_DNS_TIMEOUT_SECONDS", "2")),
        tcp_timeout_seconds=float(os.getenv("NETPULSE_TCP_TIMEOUT_SECONDS", "2")),
        dns_hostname=os.getenv("NETPULSE_DNS_HOSTNAME", "google.com"),
        dns_resolvers=_parse_csv(os.getenv("NETPULSE_DNS_RESOLVERS", "1.1.1.1,8.8.8.8")),
        tcp_targets=_parse_targets(os.getenv("NETPULSE_TCP_TARGETS", "1.1.1.1:53,8.8.8.8:53")),
    )
