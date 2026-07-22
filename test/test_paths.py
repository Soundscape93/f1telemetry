from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from f1telemetry.src import paths


class DataRootTest(unittest.TestCase):
    def test_env_override_wins_and_creates_dirs(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "f1data"
            with mock.patch.dict(os.environ, {paths._ENV_DATA_DIR: str(target)}):
                self.assertEqual(paths.data_root(), target)
                self.assertTrue(target.is_dir())
                self.assertEqual(paths.captures_dir(), target / "captures")
                self.assertTrue((target / "captures").is_dir())
                self.assertTrue(paths.trace_dir().is_dir())
                self.assertTrue(paths.rosters_dir().is_dir())
                self.assertTrue(paths.logs_dir().is_dir())
                self.assertEqual(paths.db_path(), target / "f1league.db")
                self.assertTrue(paths.db_url().startswith("sqlite:///"))
                self.assertIn("f1league.db", paths.db_url())

    def test_dev_data_root_is_cwd(self):
        with TemporaryDirectory() as tmp:
            env_without_override = {k: v for k, v in os.environ.items()
                                    if k != paths._ENV_DATA_DIR}
            with mock.patch.dict(os.environ, env_without_override, clear=True), \
                    mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                self.assertFalse(paths.is_frozen())
                self.assertEqual(paths.data_root(), Path(tmp))


class ResourcePathTest(unittest.TestCase):
    def test_flags_dir_resolves_in_source_tree(self):
        flags = paths.resource_path("ui", "assets", "flags")
        self.assertTrue(flags.is_dir(), flags)
        self.assertTrue((flags / "gb.svg").exists())


if __name__ == "__main__":
    unittest.main()