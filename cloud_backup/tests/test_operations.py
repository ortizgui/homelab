from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.configuration import default_config
from app.operations import build_backup_command, normalize_bandwidth_limit, recover_interrupted_backup, run_post_failure_prune
from app.runtime import CommandResult


class BackupCommandTests(unittest.TestCase):
    def test_default_exclusions_keep_iso_files_included(self) -> None:
        self.assertNotIn("*.iso", default_config()["exclusions"])

    def test_normalize_bandwidth_limit_accepts_human_readable_megabytes(self) -> None:
        self.assertEqual(normalize_bandwidth_limit("3M"), ["--limit-upload", "3072"])

    def test_normalize_bandwidth_limit_accepts_explicit_flag_format(self) -> None:
        self.assertEqual(normalize_bandwidth_limit("--limit-upload 512K"), ["--limit-upload", "512"])

    def test_build_backup_command_uses_normalized_bandwidth_limit(self) -> None:
        config = default_config()
        config["limits"]["bandwidth_limit"] = "3M"

        command = build_backup_command(config, "manual")

        self.assertIn("--limit-upload", command)
        index = command.index("--limit-upload")
        self.assertEqual(command[index + 1], "3072")

    def test_run_post_failure_prune_logs_context(self) -> None:
        config = default_config()
        result = CommandResult(code=0, stdout='{"ok":true}', stderr="", command=["restic", "prune", "--json"])

        with patch("app.operations.run_command", return_value=result) as run_command_mock:
            with patch("app.operations.append_log") as append_log_mock:
                payload = run_post_failure_prune(config, "backup")

        run_command_mock.assert_called_once()
        append_log_mock.assert_called_once()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "prune")
        self.assertEqual(payload["phase"], "post-failure")
        self.assertEqual(payload["trigger_action"], "backup")

    def test_recover_interrupted_backup_runs_cleanup_once(self) -> None:
        interrupted = {"action": "backup", "started_at": "2026-03-29T03:00:00+00:00", "tag": "scheduled"}
        prune_payload = {"ok": True, "action": "prune", "phase": "post-failure", "trigger_action": "backup"}

        with patch("app.operations.interrupted_run", return_value=interrupted):
            with patch("app.operations.load_config", return_value=default_config()):
                with patch("app.operations.run_post_failure_prune", return_value=prune_payload) as prune_mock:
                    with patch("app.operations.append_log") as append_log_mock:
                        with patch("app.operations.end_run") as end_run_mock:
                            payload = recover_interrupted_backup()

        prune_mock.assert_called_once()
        append_log_mock.assert_called_once()
        end_run_mock.assert_called_once()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "recovery")
        self.assertEqual(payload["phase"], "startup-prune")
        self.assertEqual(payload["interrupted_run"], interrupted)


if __name__ == "__main__":
    unittest.main()
