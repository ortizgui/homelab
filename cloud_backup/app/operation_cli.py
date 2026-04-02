from __future__ import annotations

import json
import sys

from .operations import dashboard_summary, healthcheck, preflight, remote_storage_quota, restore_snapshot, run_backup, run_forget, run_prune, status, unlock_repository


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "status":
        payload = status()
    elif action == "summary":
        payload = dashboard_summary()
    elif action == "remote-quota":
        payload = remote_storage_quota()
    elif action == "healthcheck":
        payload = healthcheck()
    elif action == "preflight":
        payload = preflight()
    elif action == "backup":
        tag = sys.argv[2] if len(sys.argv) > 2 else "manual"
        payload = run_backup(tag)
    elif action == "forget":
        payload = run_forget()
    elif action == "prune":
        payload = run_prune()
    elif action == "unlock":
        payload = unlock_repository()
    elif action == "restore":
        if len(sys.argv) < 4:
            raise SystemExit("usage: restore <snapshot_id> <target> [include_path]")
        payload = restore_snapshot(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        raise SystemExit(f"unknown action: {action}")
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
