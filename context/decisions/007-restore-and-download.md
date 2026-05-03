# Decision: Restore & Download via Web UI

## Context
Backup validation required SSH access to the server. No way to restore selected files from the web UI. Existing restore feature wrote to server filesystem only, requiring manual tar/scp to transfer.

## Decision
Add web-based restore with file browser and tar.gz download:

1. **Snapshot browser**: Dropdown populated from `/api/snapshots`. Select snapshot to browse.
2. **File tree browser**: `restic ls <snapshot> <path>` lists direct children. Lazy-loaded on directory click.
3. **Multi-select**: Checkboxes on files/directories. Selected paths tracked on client side.
4. **Restore & Pack**: `restic restore --include <path>` to temp dir, then `tar -czf` the result.
5. **Download**: Serve .tar.gz via HTTP, auto-delete after download.

## Rationale
- Validate backup integrity without SSH access
- Restore individual files/folders without restoring 1.3T full backup
- Browser download works for typical restore sizes (<5GB)
- Vanilla JS, no framework dependencies
- Filename-based path validation prevents directory traversal

## Alternatives Considered
- **rsync/NFS mount**: More complex setup, requires network config changes
- **Streaming restore (tar via pipe)**: Higher complexity, harder to monitor progress
- **CLI-only**: SSH required, defeats the "web UI" purpose

## API Design
```
GET  /api/snapshots                        → {snapshots: [{id, time, tags, paths}]}
GET  /api/browse-snapshot/<id>?path=/dir   → {entries: [{name, type, path}]}
POST /api/actions/restore-pack             → {download_url, file_name, file_size}
     body: {snapshot_id, paths[], target_name?}
GET  /api/restore-download/<file>.tar.gz   → application/gzip stream
```

## Security
- Restore path validated inside container restore_root
- Download path validated against restore_root (Path traversal guard)
- Auto-cleanup: tar.gz deleted after download or after 60min via cleanup cron

## Related
- [Decision: Cloud Backup Architecture](../decisions/002-cloud-backup-architecture.md)
- [Decision: Preflight Remote Cache and Scheduler Logging](../decisions/006-preflight-cache.md)

## Status
- **Created**: 2026-05-03
- **Status**: Active
