# Changelog

## [Current State] - Context Mesh Added

### Existing Features (documented)
- **Cloud Backup** - Encrypted backup stack (restic + rclone) with safety gates, scheduling, web UI, and API
- **Disk Health Monitoring** - SMART health, temperature, and RAID monitoring with Telegram alerts and bot
- **Network Connectivity Monitoring (Netpulse)** - TCP/DNS probing, status classification, SQLite storage, web dashboard
- **VPN Remote Access** - Tailscale-based secure remote LAN access with subnet routing and exit nodes

### Tech Stack (documented)
- Python 3.11+ (Flask, dnspython, stdlib http.server)
- Bash + smartmontools + mdadm + jq + curl
- Docker + Docker Compose (multi-arch)
- restic v0.17.3 + rclone v1.69.2
- SQLite
- Tailscale v1.92.5 (WireGuard)
- systemd timers/services
- nginx
- Vanilla HTML/CSS/JS

### Patterns Identified
- Safety Gate Pipeline
- JSON HTTP API Server (stdlib)
- SQLite Rollup Tables
- Shell Script Modular Monitoring

---
*Context Mesh added: 2026-05-03*
*This changelog documents the state when Context Mesh was added.*
*Future changes will be tracked below.*

## [2026-05-03] Preflight Caching, Scheduler Logging, Token Detection

### Changed
- **Preflight remote cache** (TTL 15 min): Remote connectivity and repository access checks cached. Local checks always fresh. Short-circuit on local failure before hitting Google API.
- **Lightweight status endpoints**: `/engine/status` and `/api/status` return cached dashboard summary (zero API calls).
- **Scheduler logging**: Startup, job triggers, results, and errors now logged to stdout/stderr. Visible via `docker logs cloud-backup-scheduler`.

### Added
- **Token expiry detection**: `check_rclone_token_expiry()` parses rclone.conf OAuth token on preflight cache miss, warns if expiring within 7 days.
- **Preflight cache helpers**: `_get_preflight_cache()`, `_set_preflight_cache()`, `_invalidate_preflight_cache()` with thread-safe lock.

### Fixed
- Silent exception swallowing in scheduler (`except Exception: pass` → errors now logged to stderr).
- Status page triggering full preflight + snapshots + stats on every load (4-5 Google API calls per reload).

### Related
- [Decision: Preflight Remote Cache and Scheduler Logging](../decisions/006-preflight-cache.md)

## [2026-05-03] Restore & Download via Web UI

### Added
- **Snapshot browser**: Dropdown in Restore panel populated from `/api/snapshots`.
- **File tree browser**: Navigate snapshot directories via `restic ls`. Lazy-load children on click. Up/down navigation.
- **Multi-select restore**: Check files/directories to restore. Selected count displayed.
- **Restore & Pack**: Backend runs `restic restore --include <path>`, packs as `.tar.gz`, returns download URL.
- **HTTP file download**: `GET /api/restore-download/<file>` streams `.tar.gz` with auto-delete after transfer.
- **Cleanup**: `cleanup_old_restore_packs()` removes stale `.tar.gz` files older than 1 hour.

### API Endpoints (new)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/browse-snapshot/<id>?path=/dir` | List direct children in snapshot path |
| POST | `/api/actions/restore-pack` | Restore selected paths, pack as tar.gz |
| GET | `/api/restore-download/<file>` | Download restored archive (auto-delete) |

### Files Changed
| File | Change |
|------|--------|
| `app/operations.py` | +`browse_snapshot()`, +`restore_and_pack()`, +`cleanup_old_restore_packs()` |
| `app/engine_server.py` | +GET `/engine/browse-snapshot/<id>`, +POST `/engine/restore-pack` |
| `app/api_server.py` | +GET `/api/restore-download/`, +proxy to engine for browse/restore-pack |
| `web/index.html` | Redesigned restore panel with snapshot dropdown + file browser + action bar |
| `web/app.js` | Restore browser logic: snapshot list, tree nav, multi-select, download trigger |
| `web/styles.css` | File browser tree styles, download link, selected bar |

### Related
- [Decision: Restore & Download via Web UI](../decisions/007-restore-and-download.md)

## [2026-05-03] Phase 1 Performance: Config Cache + Log Buffer

### Changed
- **Config cache (TTL 5s)**: `load_config()` caches parsed config in memory. Avoids disk read on every request (engine, api, scheduler all call it). `save_config()` invalidates cache immediately.
- **In-memory log buffer**: `append_log()` writes to both disk (persistence) and in-memory `collections.deque` (max 300 entries). `list_json_logs()` reads from buffer — zero disk I/O for `/api/logs`.
- **Log truncation**: `append_log()` checks file size after write. If > 1MB, truncates to last 500 lines. Prevents unbounded growth of `operations.jsonl` / `preflight.jsonl`.

### Files Changed
| File | Change |
|------|--------|
| `app/configuration.py` | Config cache with TTL, split `load_config()` into cached wrapper + `_load_config_from_disk()` |
| `app/runtime.py` | In-memory log buffer + truncation on append |

### Related
- [Decision: Preflight Remote Cache and Scheduler Logging](../decisions/006-preflight-cache.md)

## [2026-05-03] Code Review: Resilience and Performance

### Fixed
- **JS orphaned DOM references**: `document.getElementById("run-restore")` (element removed from HTML) crashed initial page load before `loadAll()` could run. Removed old restore event listener. `document.getElementById("restore-snapshots")` wrapped in null guard.
- **scheduler-state.json corruption**: `scheduler.py:load_state()` now catches `json.JSONDecodeError`, returns `{}` instead of crashing scheduler loop.
- **config.json corruption**: `configuration.py:_load_config_from_disk()` now catches `json.JSONDecodeError`, regenerates from defaults instead of crashing engine.
- **JSONL parse tolerance**: `operations.py:list_logs()` skips corrupted lines instead of crashing. `runtime.py:list_json_logs()` uses `_safe_load()` helper.

### Files Changed
| File | Change |
|------|--------|
| `web/app.js` | Removed orphaned `run-restore` listener, null-guarded `restore-snapshots` in renderStatus() |
| `app/scheduler.py` | JSONDecodeError tolerance in load_state() |
| `app/configuration.py` | JSONDecodeError tolerance in _load_config_from_disk() |
