from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.configuration import SCHEMA_VERSION, default_config, export_bundle, migrate_config, validate_config


class ConfigValidationTests(unittest.TestCase):
    def test_default_config_is_valid(self) -> None:
        validate_config(default_config())

    def test_default_config_uses_expected_raid1_sources(self) -> None:
        config = default_config()
        enabled_paths = [source["path"] for source in config["sources"] if source["enabled"]]

        self.assertEqual(
            enabled_paths,
            [
                "/source/raid1/academic",
                "/source/raid1/backups",
                "/source/raid1/documents",
                "/source/raid1/media",
                "/source/raid1/onedrive-import",
                "/source/raid1/personal",
                "/source/raid1/professional",
                "/source/raid1/projects",
                "/source/raid1/shared",
                "/source/raid1/software",
            ],
        )
        project_entry = next(source for source in config["sources"] if source["path"] == "/source/raid1/projects")
        self.assertTrue(project_entry["allow_empty"])

    def test_invalid_schema_version_fails(self) -> None:
        config = default_config()
        config["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_repository_must_match_remote(self) -> None:
        config = default_config()
        config["provider"]["repository"] = "rclone:other:/backups/restic"
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_migrate_legacy_config_adds_missing_sections(self) -> None:
        config = default_config()
        del config["notifications"]
        del config["security"]
        del config["limits"]

        migrated = migrate_config(config)

        validate_config(migrated)
        self.assertIn("notifications", migrated)
        self.assertIn("security", migrated)
        self.assertIn("limits", migrated)

    def test_migrate_config_preserves_existing_values(self) -> None:
        config = {
            "schema_version": SCHEMA_VERSION,
            "general": {
                "instance_name": "srv-backup",
                "timezone": "America/Sao_Paulo",
                "authorized_roots": ["/data/a"],
                "restore_root": "/restore",
                "log_retention_days": 10,
            },
            "provider": {
                "type": "google-drive",
                "remote_name": "corp",
                "repository": "rclone:corp:/restic",
                "restic_password": "secret",
                "rclone_config": "",
            },
            "sources": [{"path": "/data/a", "enabled": True, "allow_empty": False}],
            "exclusions": [],
            "schedule": {
                "backup": {"enabled": True, "days_of_week": [1], "time": "01:00"},
                "forget": {"enabled": False, "days_of_week": [2], "time": "02:00"},
                "prune": {"enabled": False, "days_of_week": [3], "time": "03:00"},
            },
            "retention": {
                "keep_last": 1,
                "keep_daily": 2,
                "keep_weekly": 3,
                "keep_monthly": 4,
            },
        }

        migrated = migrate_config(config)

        self.assertEqual(migrated["general"]["instance_name"], "srv-backup")
        self.assertEqual(migrated["provider"]["remote_name"], "corp")
        self.assertEqual(migrated["retention"]["keep_monthly"], 4)
        self.assertIn("notifications", migrated)

    def test_export_bundle_includes_provider_secrets_for_restore(self) -> None:
        config = default_config()
        config["provider"]["restic_password"] = "super-secret"
        config["provider"]["rclone_config"] = "[gdrive]\ntype = drive\n"

        bundle = export_bundle(config)

        self.assertEqual(bundle["schema_version"], SCHEMA_VERSION)
        self.assertEqual(bundle["config"]["provider"]["restic_password"], "super-secret")
        self.assertEqual(bundle["config"]["provider"]["rclone_config"], "[gdrive]\ntype = drive\n")
        self.assertEqual(config["provider"]["restic_password"], "super-secret")


if __name__ == "__main__":
    unittest.main()
