from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from f1telemetry.src import user_guide


def _make_dirs(tmp: str) -> tuple[Path, Path]:
    app_dir, docs_dir = Path(tmp) / "app", Path(tmp) / "docs"
    app_dir.mkdir()
    docs_dir.mkdir()
    return app_dir, docs_dir


class ResolveGuideTest(unittest.TestCase):
    def test_pdf_beside_the_exe_wins_over_the_source_markdown(self):
        with TemporaryDirectory() as tmp:
            app_dir, docs_dir = _make_dirs(tmp)
            (app_dir / user_guide.PDF_NAME).write_bytes(b"%PDF-1.4\n")
            (docs_dir / user_guide.MD_NAME).write_text("# guide", encoding="utf-8")

            target = user_guide.resolve_guide(app_dir=app_dir, docs_dir=docs_dir)
            self.assertTrue(target.is_local)
            self.assertEqual(target.path, app_dir / user_guide.PDF_NAME)

    def test_source_markdown_used_when_no_pdf_was_shipped(self):
        with TemporaryDirectory() as tmp:
            app_dir, docs_dir = _make_dirs(tmp)
            (docs_dir / user_guide.MD_NAME).write_text("# guide", encoding="utf-8")

            target = user_guide.resolve_guide(app_dir=app_dir, docs_dir=docs_dir)
            self.assertEqual(target.path, docs_dir / user_guide.MD_NAME)

    def test_github_fallback_when_nothing_is_local(self):
        """The action must never dead-end - e.g. someone who unzipped only the exe."""
        with TemporaryDirectory() as tmp:
            app_dir, docs_dir = _make_dirs(tmp)
            target = user_guide.resolve_guide(app_dir=app_dir, docs_dir=docs_dir)
            self.assertFalse(target.is_local)
            self.assertEqual(target.url, user_guide.github_url())
            self.assertIn("/blob/main/docs/USER_GUIDE.md", target.url)

    def test_defaults_resolve_the_markdown_in_this_checkout(self):
        target = user_guide.resolve_guide()
        self.assertTrue(target.is_local)
        self.assertEqual(target.path.name, user_guide.MD_NAME)


class ResolveNoticesTest(unittest.TestCase):
    def test_pdf_beside_the_exe_wins_over_the_markdown(self):
        """F9: the PDF is the readable one, so a release build must open it, not NOTICE.md."""
        with TemporaryDirectory() as tmp:
            app_dir, _ = _make_dirs(tmp)
            (app_dir / user_guide.NOTICES_PDF_NAME).write_bytes(b"%PDF-1.4\n")
            (app_dir / user_guide.NOTICES_NAME).write_text("# Notices", encoding="utf-8")

            target = user_guide.resolve_notices(app_dir=app_dir)
            self.assertTrue(target.is_local)
            self.assertEqual(target.path, app_dir / user_guide.NOTICES_PDF_NAME)

    def test_markdown_used_when_no_pdf_was_generated(self):
        """The source run, and a build whose PDF step never produced one."""
        with TemporaryDirectory() as tmp:
            app_dir, _ = _make_dirs(tmp)
            (app_dir / user_guide.NOTICES_NAME).write_text("# Notices", encoding="utf-8")

            target = user_guide.resolve_notices(app_dir=app_dir)
            self.assertTrue(target.is_local)
            self.assertEqual(target.path, app_dir / user_guide.NOTICES_NAME)

    def test_github_fallback_when_the_notices_were_not_unzipped(self):
        """Never dead-ends: the LGPL notice for the bundled Qt must reach the user either way."""
        with TemporaryDirectory() as tmp:
            app_dir, _ = _make_dirs(tmp)

            target = user_guide.resolve_notices(app_dir=app_dir)
            self.assertFalse(target.is_local)
            self.assertEqual(target.url, user_guide.notices_url())
            self.assertIn("/blob/main/NOTICE.md", target.url)

    def test_defaults_resolve_the_notices_in_this_checkout(self):
        """app_dir() is the repo root in a source run - which holds NOTICE.md and, because the
        PDF is gitignored, never NOTICE.pdf. Same assumption test_defaults_resolve_the_markdown_
        in_this_checkout makes about USER_GUIDE.pdf."""
        target = user_guide.resolve_notices()
        self.assertTrue(target.is_local)
        self.assertEqual(target.path.name, user_guide.NOTICES_NAME)


if __name__ == "__main__":
    unittest.main()
