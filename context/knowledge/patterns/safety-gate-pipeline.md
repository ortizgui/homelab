# Pattern: Safety Gate Pipeline

## Description
A chain of validation checks that must all pass before a state-changing operation is allowed to proceed. Each check is independent; failures are collected and reported as a batch. Local checks run first (fail fast); remote checks are cached with TTL to avoid excessive API calls.

## When to Use
- Before any operation that modifies remote/cloud state
- When multiple preconditions must be verified (mounts, connectivity, health)
- When operations should be blocked early rather than failing mid-execution
- When remote API calls are expensive or rate-limited — cache them and short-circuit on local failures

## Pattern

```python
def preflight(config: dict) -> dict:
    # Local checks first (zero API calls) — fail fast
    mount_results = check_mounts(config)
    source_results = check_sources(config)
    disk_health_result = check_disk_health(config)

    failures = []
    if any(not m["exists"] or not m["is_dir"] for m in mount_results):
        failures.append("Expected mountpoint missing")
    if any(s["critical_failure"] for s in source_results):
        failures.append("Source validation failed")
    if not disk_health_result["ok"]:
        failures.append("Storage health gate failed")

    # Short-circuit: skip remote API calls if local checks fail
    if failures:
        return json_response(False, failures=failures, ...)

    # Remote checks cached with TTL to reduce API calls
    cached = get_preflight_cache()
    if cached:
        remote_result = cached["remote_result"]
        repository_result = cached["repository_result"]
    else:
        remote_result = check_remote_connectivity(config)
        repository_result = check_repository_access(config)
        set_preflight_cache(remote_result, repository_result)

    if not remote_result["ok"]:
        failures.append("Remote connectivity failed")
    if not repository_result["ok"]:
        failures.append("Repository access failed")

    return json_response(len(failures) == 0, failures=failures, ...)
```

Key design points:
- **Local-first**: Mount, source, and disk health checks run every time (zero external API calls).
- **Short-circuit**: If any local check fails, skip remote API calls entirely — the backup can't proceed anyway.
- **TTL cache**: Remote connectivity and repository access checks are cached for 15 minutes to avoid hammering the Google Drive API on status page reloads.

## Example

From `cloud_backup/app/operations.py`:
```python
def run_backup(tag: str = "manual") -> dict:
    recover_interrupted_backup()
    config = load_config()
    gate = preflight(config)           # Safety gate runs FIRST
    if not gate["ok"]:
        notify(config, "error", "Backup blocked", "\n".join(gate["failures"]))
        return gate                     # Blocked before any cloud mutation
    # ... proceed with backup
```

## Files Using This Pattern
- `cloud_backup/app/operations.py` - preflight(), run_backup(), run_forget(), run_prune()
- `cloud_backup/app/engine_server.py` - /engine/preflight endpoint, /engine/status endpoint
- `cloud_backup/app/api_server.py` - /api/status endpoint

## Related
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)
- [Decision: Preflight Remote Cache and Scheduler Logging](../decisions/006-preflight-cache.md)
- [Feature: Cloud Backup](../intent/feature-cloud-backup.md)

## Status
- **Created**: 2026-05-03
- **Updated**: 2026-05-03 (caching + short-circuit)
- **Status**: Active
