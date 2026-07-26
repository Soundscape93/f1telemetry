"""The release-bump arithmetic and changelog rewrite.

``packaging/`` is not an importable package (and must not become one - the PyInstaller spec
treats it as plain files), so the script is loaded by path.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import unittest

from f1telemetry.src import paths


def _load(name: str):
    path = paths.app_dir() / "packaging" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_packaging_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load("bump_version")

_READY = """# Changelog

## Unreleased

<!-- instructions -->

- Something visible changed.

**Re-ingest needed: no**

## v0.1.0 — 2026-01-01

- The first one.
"""


class NextVersionTest(unittest.TestCase):
    def test_each_level(self):
        for level, expected in (("major", "1.0.0"), ("minor", "0.3.0"), ("patch", "0.2.4")):
            with self.subTest(level=level):
                self.assertEqual(bump_version.next_version("0.2.3", level), expected)

    def test_unknown_level_is_rejected(self):
        with self.assertRaises(ValueError):
            bump_version.next_version("0.2.3", "huge")


class CheckTest(unittest.TestCase):
    def test_a_written_section_passes(self):
        self.assertEqual(bump_version.check(_READY), [])

    def test_placeholder_only_section_is_rejected(self):
        """The instruction comment must not count as release notes."""
        text = f"# Changelog\n\n## Unreleased\n\n{bump_version.PLACEHOLDER}\n"
        self.assertTrue(bump_version.check(text))

    def test_missing_reingest_line_is_rejected(self):
        text = "# Changelog\n\n## Unreleased\n\n- Something changed.\n"
        problems = bump_version.check(text)
        self.assertTrue(problems)
        self.assertIn("Re-ingest", problems[0])


class ReleaseUnreleasedTest(unittest.TestCase):
    def test_section_is_renamed_and_a_fresh_one_opened(self):
        out = bump_version.release_unreleased(_READY, "0.2.0", dt.date(2026, 7, 26))

        self.assertIn("## v0.2.0 — 2026-07-26", out)
        self.assertIn("- Something visible changed.", out)
        self.assertIn("## v0.1.0 — 2026-01-01", out)          # older entries survive
        self.assertIn(bump_version.PLACEHOLDER, out)          # a new Unreleased is ready
        self.assertEqual(bump_version.check(out)[0][:8], "The Unre")   # ... and is empty again

    def test_the_released_section_carries_no_instruction_comment(self):
        out = bump_version.release_unreleased(_READY, "0.2.0", dt.date(2026, 7, 26))
        released = out.split("## v0.2.0")[1].split("## v0.1.0")[0]
        self.assertNotIn("<!--", released)


if __name__ == "__main__":
    unittest.main()