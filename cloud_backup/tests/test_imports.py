from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImportSmokeTests(unittest.TestCase):
    def test_modules_import(self) -> None:
        import app.api_server  # noqa: F401
        import app.engine_server  # noqa: F401
        import app.scheduler  # noqa: F401


if __name__ == "__main__":
    unittest.main()
