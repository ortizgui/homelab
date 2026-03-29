from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.configuration import default_config
from app.operations import build_backup_command, normalize_bandwidth_limit


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


if __name__ == "__main__":
    unittest.main()
