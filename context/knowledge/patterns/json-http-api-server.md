# Pattern: JSON HTTP API Server

## Description
Lightweight HTTP API server using Python's standard library `http.server.ThreadingHTTPServer` with a custom `JsonHandler` base class that handles JSON request parsing, JSON response serialization, and CORS headers.

## When to Use
- Internal-only APIs where simplicity matters more than framework features
- When avoiding external dependencies is important
- For microservices that only need REST-like JSON endpoints

## Pattern

```python
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
import json
from urllib.parse import parse_qs, urlparse

class JsonHandler(BaseHTTPRequestHandler):
    server_version = "MyService/1.0"
    
    def parse_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(body.decode("utf-8") or "{}")
    
    def send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
        self.end_headers()
        self.wfile.write(encoded)
    
    def parsed_url(self):
        return urlparse(self.path)
    
    def query_params(self):
        return parse_qs(self.parsed_url().query)

def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8080), MyHandler)
    server.serve_forever()
```

## Files Using This Pattern
- `cloud_backup/app/http_utils.py` - JsonHandler base class
- `cloud_backup/app/api_server.py` - ApiHandler (extends JsonHandler)
- `cloud_backup/app/engine_server.py` - EngineHandler (extends JsonHandler)

## Related
- [Decision: Cloud Backup Architecture](../decisions/002-cloud-backup-architecture.md)

## Status
- **Created**: 2026-05-03
- **Status**: Active
