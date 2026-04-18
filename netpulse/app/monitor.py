from __future__ import annotations

import logging
import socket
import threading
import time
from datetime import UTC, datetime

import dns.exception
import dns.message
import dns.query
import dns.rdatatype

from .config import Settings
from .storage import Storage

LOGGER = logging.getLogger(__name__)


def tcp_probe(host: str, port: int, timeout_seconds: float) -> dict:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return {"target": f"{host}:{port}", "ok": True, "latency_ms": latency_ms}
    except OSError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "target": f"{host}:{port}",
            "ok": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def dns_probe(server: str, hostname: str, timeout_seconds: float) -> dict:
    started = time.perf_counter()
    query = dns.message.make_query(hostname, dns.rdatatype.A)
    try:
        response = dns.query.udp(query, server, timeout=timeout_seconds)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        answer_count = sum(len(answer) for answer in response.answer)
        return {
            "resolver": server,
            "hostname": hostname,
            "ok": response.rcode() == 0 and answer_count > 0,
            "latency_ms": latency_ms,
            "answers": answer_count,
        }
    except (dns.exception.DNSException, OSError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "resolver": server,
            "hostname": hostname,
            "ok": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def classify_status(tcp_results: list[dict], dns_results: list[dict]) -> tuple[str, bool, bool, bool]:
    internet_ok = any(item["ok"] for item in tcp_results)
    dns_ok = any(item["ok"] for item in dns_results)

    if internet_ok and dns_ok:
        return "healthy", True, True, False
    if internet_ok and not dns_ok:
        return "dns_issue", True, False, False
    if not internet_ok and dns_ok:
        return "degraded", False, True, False
    return "offline", False, False, True


def collect_sample(settings: Settings) -> dict:
    tcp_results = [
        tcp_probe(host, port, settings.tcp_timeout_seconds)
        for host, port in settings.tcp_targets
    ]
    dns_results = [
        dns_probe(server, settings.dns_hostname, settings.dns_timeout_seconds)
        for server in settings.dns_resolvers
    ]
    status, internet_ok, dns_ok, offline = classify_status(tcp_results, dns_results)
    return {
        "ts": datetime.now(UTC).isoformat(),
        "status": status,
        "internet_ok": internet_ok,
        "dns_ok": dns_ok,
        "offline": offline,
        "dns_hostname": settings.dns_hostname,
        "tcp_results": tcp_results,
        "dns_results": dns_results,
    }


class MonitorThread(threading.Thread):
    def __init__(self, settings: Settings, storage: Storage) -> None:
        super().__init__(name="netpulse-monitor", daemon=True)
        self.settings = settings
        self.storage = storage
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        last_prune_at = 0.0
        while not self._stop_event.is_set():
            sample = collect_sample(self.settings)
            self.storage.insert_sample(sample)
            LOGGER.info("sample recorded: status=%s ts=%s", sample["status"], sample["ts"])

            now = time.monotonic()
            if now - last_prune_at >= 3600:
                runtime = self.storage.get_runtime_settings(
                    {
                        "log_retention_days": self.settings.log_retention_days,
                        "log_max_size_mb": self.settings.log_max_size_mb,
                        "graph_retention_days": self.settings.graph_retention_days,
                    }
                )
                removed_by_age = self.storage.prune_old_samples(runtime["log_retention_days"])
                removed_by_size = self.storage.prune_samples_by_size(runtime["log_max_size_mb"])
                removed_rollups = self.storage.prune_rollups(runtime["graph_retention_days"])
                if removed_by_age or removed_by_size or removed_rollups:
                    LOGGER.info(
                        "pruned samples_by_age=%s samples_by_size=%s rollups=%s",
                        removed_by_age,
                        removed_by_size,
                        removed_rollups,
                    )
                last_prune_at = now

            self._stop_event.wait(self.settings.poll_interval_seconds)
