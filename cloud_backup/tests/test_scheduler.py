from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import scheduler


class SchedulerTests(unittest.TestCase):
    def test_run_job_records_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.scheduler.state_dir", return_value=Path(tmpdir)):
                with patch("app.scheduler.trigger", return_value={"ok": True}):
                    scheduler.run_job("backup", "/engine/backup", "2026-03-29T03:00")

                state = scheduler.load_state()
                self.assertEqual(state["backup"], "2026-03-29T03:00")

    def test_run_job_does_not_record_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.scheduler.state_dir", return_value=Path(tmpdir)):
                with patch("app.scheduler.trigger", return_value={"ok": False}):
                    scheduler.run_job("prune", "/engine/prune", "2026-03-29T03:30")

                self.assertEqual(scheduler.load_state(), {})

    def test_run_job_clears_in_flight_on_failure(self) -> None:
        self.assertTrue(scheduler.mark_in_flight("forget"))

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.scheduler.state_dir", return_value=Path(tmpdir)):
                with patch("app.scheduler.trigger", side_effect=RuntimeError("boom")):
                    scheduler.run_job("forget", "/engine/forget", "2026-03-29T04:00")

        self.assertFalse(scheduler.in_flight("forget"))


if __name__ == "__main__":
    unittest.main()
