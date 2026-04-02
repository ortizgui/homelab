from __future__ import annotations

import os
from http import HTTPStatus
from http.server import ThreadingHTTPServer

from .configuration import load_config
from .http_utils import JsonHandler
from .operations import (
    browse_path,
    dashboard_summary,
    healthcheck,
    list_logs,
    list_snapshots,
    preflight,
    repository_stats,
    restore_snapshot,
    runtime_status,
    run_backup,
    run_forget,
    run_prune,
    remote_storage_quota,
    status,
    unlock_repository,
)
from .runtime import json_response


class EngineHandler(JsonHandler):
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.options()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = self.parsed_url()
            config = load_config()
            if parsed.path == "/healthz":
                self.send_json(healthcheck())
                return
            if parsed.path == "/engine/status":
                self.send_json(status())
                return
            if parsed.path == "/engine/summary":
                self.send_json(dashboard_summary())
                return
            if parsed.path == "/engine/remote-quota":
                self.send_json(remote_storage_quota())
                return
            if parsed.path == "/engine/runtime":
                self.send_json(runtime_status())
                return
            if parsed.path == "/engine/preflight":
                self.send_json(preflight(config))
                return
            if parsed.path == "/engine/snapshots":
                self.send_json(list_snapshots())
                return
            if parsed.path == "/engine/stats":
                self.send_json(repository_stats())
                return
            if parsed.path == "/engine/logs":
                self.send_json(list_logs())
                return
            if parsed.path == "/engine/browse":
                path = self.query_params().get("path", [None])[0]
                self.send_json(browse_path(config, path))
                return
            self.send_json(json_response(False, message="Not found"), status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json(json_response(False, message=str(exc)), status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = self.parsed_url()
            payload = self.parse_json_body()
            if parsed.path == "/engine/backup":
                self.send_json(run_backup(payload.get("tag", "manual")))
                return
            if parsed.path == "/engine/forget":
                self.send_json(run_forget())
                return
            if parsed.path == "/engine/prune":
                self.send_json(run_prune())
                return
            if parsed.path == "/engine/unlock":
                self.send_json(unlock_repository())
                return
            if parsed.path == "/engine/restore":
                self.send_json(
                    restore_snapshot(
                        payload["snapshot_id"],
                        payload["target"],
                        payload.get("include_path"),
                    )
                )
                return
            self.send_json(json_response(False, message="Not found"), status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json(json_response(False, message=str(exc)), status=HTTPStatus.BAD_REQUEST)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("CLOUD_BACKUP_ENGINE_PORT", "8091"))), EngineHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
