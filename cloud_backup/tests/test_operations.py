from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.configuration import default_config
from app.operations import (
    build_backup_notification_details,
    build_backup_command,
    check_repository_access,
    format_bytes,
    format_duration,
    normalize_bandwidth_limit,
    parse_restic_progress_line,
    parse_restic_summary,
    recover_interrupted_backup,
    run_post_failure_prune,
    unlock_repository,
)
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

    def test_parse_restic_progress_status_line(self) -> None:
        payload = parse_restic_progress_line(
            '{"message_type":"status","percent_done":0.42,"total_files":100,"files_done":42,"total_bytes":1000,"bytes_done":420,"current_files":["/source/raid1/documents/file.txt"],"seconds_remaining":120}'
        )

        self.assertEqual(payload["phase"], "running")
        self.assertEqual(payload["percent_done"], 0.42)
        self.assertEqual(payload["files_done"], 42)
        self.assertEqual(payload["current_file"], "/source/raid1/documents/file.txt")

    def test_parse_restic_progress_summary_line(self) -> None:
        payload = parse_restic_progress_line(
            '{"message_type":"summary","files_new":2,"files_changed":3,"files_unmodified":5,"total_files_processed":10,"total_bytes_processed":2048,"snapshot_id":"abc123"}'
        )

        self.assertEqual(payload["phase"], "finalizing")
        self.assertEqual(payload["snapshot_id"], "abc123")
        self.assertEqual(payload["total_files_processed"], 10)

    def test_parse_restic_summary_returns_latest_summary(self) -> None:
        stdout = "\n".join(
            [
                '{"message_type":"status","percent_done":0.4}',
                '{"message_type":"summary","snapshot_id":"old","total_files_processed":10}',
                '{"message_type":"summary","snapshot_id":"new","total_files_processed":20}',
            ]
        )

        payload = parse_restic_summary(stdout)

        self.assertEqual(payload["snapshot_id"], "new")
        self.assertEqual(payload["total_files_processed"], 20)

    def test_build_backup_notification_details_for_success(self) -> None:
        config = default_config()
        result = CommandResult(code=0, stdout="", stderr="", command=["restic", "backup"])
        summary = {
            "snapshot_id": "abc123",
            "total_files_processed": 42,
            "files_new": 5,
            "files_changed": 4,
            "data_added": 4096,
            "total_bytes_processed": 16384,
            "total_duration": 125,
        }

        details = build_backup_notification_details(
            config,
            "scheduled",
            result,
            summary,
            snapshot_info={"ok": True, "count": 11, "latest_id": "abc123"},
        )

        self.assertIn("Tag: scheduled", details)
        self.assertIn("Snapshot: abc123", details)
        self.assertIn("Arquivos processados: 42", details)
        self.assertIn("Snapshots no repositorio: 11", details)
        self.assertIn("Duracao: 2m 5s", details)

    def test_build_backup_notification_details_for_failure(self) -> None:
        config = default_config()
        result = CommandResult(code=1, stdout="", stderr="line 1\nfatal: upload failed", command=["restic", "backup"])

        details = build_backup_notification_details(
            config,
            "manual",
            result,
            None,
            snapshot_info={"ok": False, "count": 0, "stderr": "repository unavailable"},
            post_failure_prune={"ok": True},
        )

        self.assertIn("Tag: manual", details)
        self.assertIn("Motivo: fatal: upload failed", details)
        self.assertIn("Prune de recuperacao: ok", details)

    def test_format_helpers_render_human_readable_values(self) -> None:
        self.assertEqual(format_bytes(2048), "2.0 KiB")
        self.assertEqual(format_duration(3665), "1h 1m 5s")

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

    def test_repository_access_timeout_is_reported_without_traceback(self) -> None:
        config = default_config()
        timeout_result = CommandResult(
            code=124,
            stdout="",
            stderr="Command timed out after 30s: restic cat config",
            command=["restic", "cat", "config"],
        )

        with patch("app.operations.run_command", side_effect=[timeout_result, timeout_result]):
            payload = check_repository_access(config)

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["initialized"])
        self.assertIn("timed out", payload["stderr"].lower())

    def test_unlock_repository_uses_restic_env_and_logs(self) -> None:
        result = CommandResult(code=0, stdout="unlocked", stderr="", command=["restic", "unlock", "--remove-all"])

        with patch("app.operations.load_config", return_value=default_config()):
            with patch("app.operations.run_command", return_value=result) as run_command_mock:
                with patch("app.operations.append_log") as append_log_mock:
                    payload = unlock_repository()

        run_command_mock.assert_called_once()
        append_log_mock.assert_called_once()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "unlock")

    def test_interrupted_run_ignores_active_pid(self) -> None:
        from app import runtime

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "current-run.json"
            state_path.write_text(
                json.dumps({"action": "backup", "started_at": "2026-03-29T03:00:00+00:00", "tag": "scheduled", "pid": 321}),
                encoding="utf-8",
            )

            with patch("app.runtime.current_run_state_file", return_value=state_path):
                with patch("app.runtime.os.kill", return_value=None) as kill_mock:
                    payload = runtime.interrupted_run()

        kill_mock.assert_called_once_with(321, 0)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
