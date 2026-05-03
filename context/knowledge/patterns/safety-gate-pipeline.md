# Pattern: Safety Gate Pipeline

## Description
A chain of validation checks that must all pass before a state-changing operation is allowed to proceed. Each check is independent; failures are collected and reported as a batch.

## When to Use
- Before any operation that modifies remote/cloud state
- When multiple preconditions must be verified (mounts, connectivity, health)
- When operations should be blocked early rather than failing mid-execution

## Pattern

```python
def preflight(config: dict) -> dict:
    results = {
        "mounts": check_mounts(config),
        "sources": check_sources(config),
        "remote": check_remote_connectivity(config),
        "disk_health": check_disk_health(config),
        "repository": check_repository_access(config),
    }
    failures = []
    if not all(mount["exists"] for mount in results["mounts"]):
        failures.append("Expected mountpoint missing")
    if any(src["critical_failure"] for src in results["sources"]):
        failures.append("Source validation failed")
    if not results["remote"]["ok"]:
        failures.append("Remote connectivity failed")
    if not results["disk_health"]["ok"]:
        failures.append("Storage health gate failed")
    if not results["repository"]["ok"]:
        failures.append("Repository access failed")
    
    return json_response(
        len(failures) == 0,
        message="Preflight passed" if not failures else "Preflight blocked",
        failures=failures,
        **results,
    )
```

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
- `cloud_backup/app/engine_server.py` - /engine/preflight endpoint

## Related
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)
- [Feature: Cloud Backup](../intent/feature-cloud-backup.md)

## Status
- **Created**: 2026-05-03
- **Status**: Active
