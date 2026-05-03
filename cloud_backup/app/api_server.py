from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

from .configuration import coerce_import_config, export_bundle, load_config, save_config, validate_config
from .http_utils import JsonHandler
from .operations import cached_dashboard_summary, load_dashboard_cache
from .runtime import json_response


ENGINE_URL = os.getenv("CLOUD_BACKUP_ENGINE_URL", "http://backup-engine:8091")


def engine_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{ENGINE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60 * 60) as response:
        return json.loads(response.read().decode("utf-8"))


class ApiHandler(JsonHandler):
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.options()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = self.parsed_url()
            config = load_config()
            if parsed.path == "/healthz":
                self.send_json(json_response(True, service="api"))
                return
            if parsed.path == "/api/config":
                self.send_json(json_response(True, config=config))
                return
            if parsed.path == "/api/config/export":
                self.send_json(json_response(True, bundle=export_bundle(config)))
                return
            if parsed.path == "/api/config/validate":
                validate_config(config)
                self.send_json(json_response(True, message="Configuration is valid"))
                return
            if parsed.path == "/api/status":
                self.send_json(cached_dashboard_summary())
                return
            if parsed.path == "/api/summary":
                self.send_json(cached_dashboard_summary())
                return
            if parsed.path == "/api/remote-quota":
                cache = load_dashboard_cache().get("remote_quota")
                if cache:
                    payload = json_response(True, **cache)
                else:
                    payload = json_response(False, message="Remote quota cache unavailable", quota={})
                self.send_json(payload)
                return
            if parsed.path == "/api/runtime":
                self.send_json(engine_request("GET", "/engine/runtime"))
                return
            if parsed.path == "/api/preflight":
                self.send_json(engine_request("GET", "/engine/preflight"))
                return
            if parsed.path == "/api/snapshots":
                self.send_json(engine_request("GET", "/engine/snapshots"))
                return
            if parsed.path == "/api/stats":
                self.send_json(engine_request("GET", "/engine/stats"))
                return
            if parsed.path == "/api/logs":
                self.send_json(engine_request("GET", "/engine/logs"))
                return
            if parsed.path == "/api/browse":
                query = self.query_params().get("path", [None])[0]
                suffix = f"?path={urllib.parse.quote(query)}" if query else ""
                self.send_json(engine_request("GET", f"/engine/browse{suffix}"))
                return
            if parsed.path.startswith("/api/browse-snapshot/"):
                snapshot_id = parsed.path[len("/api/browse-snapshot/"):]
                query_path = self.query_params().get("path", [None])[0]
                suffix = f"?path={urllib.parse.quote(query_path)}" if query_path else ""
                self.send_json(engine_request("GET", f"/engine/browse-snapshot/{snapshot_id}{suffix}"))
                return
            if parsed.path.startswith("/api/restore-download/"):
                file_name = parsed.path[len("/api/restore-download/"):]
                config = load_config()
                restore_root = Path(config["general"]["restore_root"]).resolve()
                file_path = restore_root / file_name
                if not file_path.exists() or not file_path.is_file():
                    self.send_json(json_response(False, message="File not found"), status=HTTPStatus.NOT_FOUND)
                    return
                if not str(file_path.resolve()).startswith(str(restore_root)):
                    self.send_json(json_response(False, message="Invalid file"), status=HTTPStatus.FORBIDDEN)
                    return
                try:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Disposition", f'attachment; filename="{file_name}"')
                    self.send_header("Content-Length", str(file_path.stat().st_size))
                    self.end_headers()
                    with open(file_path, "rb") as fh:
                        import shutil
                        shutil.copyfileobj(fh, self.wfile)
                    file_path.unlink(missing_ok=True)
                    return
                except (BrokenPipeError, ConnectionResetError):
                    file_path.unlink(missing_ok=True)
                    return
            self.send_json(json_response(False, message="Not found"), status=HTTPStatus.NOT_FOUND)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") or "{}"
            self.send_json(json.loads(body), status=exc.code)
        except Exception as exc:
            self.send_json(json_response(False, message=str(exc)), status=HTTPStatus.BAD_REQUEST)

    def do_PUT(self) -> None:  # noqa: N802
        try:
            if self.parsed_url().path != "/api/config":
                self.send_json(json_response(False, message="Not found"), status=HTTPStatus.NOT_FOUND)
                return
            payload = self.parse_json_body()
            config = payload.get("config")
            if not isinstance(config, dict):
                raise ValueError("Request body must include config object")
            saved = save_config(config)
            self.send_json(json_response(True, config=saved))
        except Exception as exc:
            self.send_json(json_response(False, message=str(exc)), status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = self.parsed_url()
            payload = self.parse_json_body()
            if parsed.path == "/api/config/import":
                imported = coerce_import_config(payload)
                saved = save_config(imported)
                self.send_json(json_response(True, config=saved))
                return
            if parsed.path == "/api/config/validate":
                validate_config(payload.get("config", {}))
                self.send_json(json_response(True, message="Configuration is valid"))
                return
            if parsed.path == "/api/actions/test-remote":
                self.send_json(engine_request("GET", "/engine/preflight"))
                return
            if parsed.path == "/api/actions/backup":
                self.send_json(engine_request("POST", "/engine/backup", payload))
                return
            if parsed.path == "/api/actions/forget":
                self.send_json(engine_request("POST", "/engine/forget", payload))
                return
            if parsed.path == "/api/actions/prune":
                self.send_json(engine_request("POST", "/engine/prune", payload))
                return
            if parsed.path == "/api/actions/restore":
                self.send_json(engine_request("POST", "/engine/restore", payload))
                return
            if parsed.path == "/api/actions/restore-pack":
                self.send_json(engine_request("POST", "/engine/restore-pack", payload))
                return
            self.send_json(json_response(False, message="Not found"), status=HTTPStatus.NOT_FOUND)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") or "{}"
            self.send_json(json.loads(body), status=exc.code)
        except Exception as exc:
            self.send_json(json_response(False, message=str(exc)), status=HTTPStatus.BAD_REQUEST)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("CLOUD_BACKUP_API_LISTEN_PORT", "8080"))), ApiHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
