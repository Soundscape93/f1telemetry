"""The startup capability self-check.

Qt-free, like every suite here. The coverage sits where a packaged build can actually fail: the
flag probe (bundled *data* — what a spec edit drops), the aggregation, and the log lines. The
import probes are only smoke-tested against this checkout, because asserting anything stronger
would just be asserting what happens to be installed on this machine.
"""
from __future__ import annotations

import dataclasses
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from f1telemetry.src import capabilities as caps


def _ok(name: str = "charts") -> caps.Capability:
    return caps.Capability(name, "Label", True, "resolved", "")


def _bad(name: str = "charts", consequence: str = "no charts") -> caps.Capability:
    return caps.Capability(name, "Label", False, "not shipped", consequence)


class CapabilityTest(unittest.TestCase):
    def test_is_frozen(self):
        """These are handed to the UI and logged; nothing downstream may rewrite a result."""
        cap = _ok()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cap.ok = False              # type: ignore[misc]


class FlagProbeTest(unittest.TestCase):
    """The one probe with a failure mode we can reproduce: the bundled assets are gone."""

    def _probe_against(self, directory: Path) -> caps.Capability:
        original = caps.resource_path
        caps.resource_path = lambda *parts: directory
        try:
            return caps._probe_flags()
        finally:
            caps.resource_path = original

    def test_ok_when_the_folder_holds_svgs(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "gb.svg").write_text("<svg/>")
            result = self._probe_against(Path(tmp))
        self.assertTrue(result.ok)
        self.assertIn("1 flag", result.detail, "the healthy detail should say how many")

    def test_degraded_when_the_folder_is_empty(self):
        """A spec that drops the datas entry leaves the directory resolvable but bare."""
        with TemporaryDirectory() as tmp:
            result = self._probe_against(Path(tmp))
        self.assertFalse(result.ok)
        self.assertIn("no flag assets", result.detail)
        self.assertTrue(result.consequence, "a degraded capability must say what is lost")

    def test_degraded_when_the_folder_does_not_exist(self):
        with TemporaryDirectory() as tmp:
            result = self._probe_against(Path(tmp) / "gone")
        self.assertFalse(result.ok)

    def test_non_svg_content_does_not_count(self):
        """ATTRIBUTION.md ships in that folder; it is not a flag."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "ATTRIBUTION.md").write_text("credits")
            self.assertFalse(self._probe_against(Path(tmp)).ok)


class AggregateTest(unittest.TestCase):
    def test_degraded_selects_only_the_failures(self):
        probed = (_ok("charts"), _bad("compression"), _ok("traces"), _bad("flags"))
        self.assertEqual(("compression", "flags"), tuple(c.name for c in caps.degraded(probed)))

    def test_degraded_is_empty_on_a_healthy_build(self):
        self.assertEqual((), caps.degraded((_ok("charts"), _ok("traces"))))

    def test_results_keep_probe_order(self):
        order = caps.check_capabilities(probes=(lambda: _ok("a"), lambda: _bad("b"), lambda: _ok("c")))
        self.assertEqual(("a", "b", "c"), tuple(c.name for c in order))

    def test_a_broken_probe_is_reported_as_degraded(self):
        """A self-check that can crash start-up is worse than no self-check - so it fails loud."""
        def explode():
            raise RuntimeError("probe bug")

        result = caps.check_capabilities(probes=(lambda: _ok("charts"), explode))

        self.assertEqual(2, len(result), "the broken probe must still produce a result")
        broken = result[1]
        self.assertFalse(broken.ok)
        self.assertIn("probe bug", broken.detail)
        self.assertIn("the check itself failed", broken.detail)


class LoggingTest(unittest.TestCase):
    """``assertLogs`` formats each record, so a bad format string fails here rather than
    disappearing into logging's internal error handler at runtime."""

    def test_a_healthy_capability_logs_at_info(self):
        with self.assertLogs(caps.log, level=logging.INFO) as logged:
            caps.log_capabilities((_ok("charts"),))
        self.assertEqual(1, len(logged.output))
        self.assertIn("INFO", logged.output[0])
        self.assertIn("charts: ok", logged.output[0])

    def test_a_degraded_capability_logs_its_detail_at_warning(self):
        with self.assertLogs(caps.log, level=logging.WARNING) as logged:
            caps.log_capabilities((_bad("flags"),))
        self.assertEqual(1, len(logged.output))
        self.assertIn("WARNING", logged.output[0])
        self.assertIn("flags: DEGRADED", logged.output[0])
        self.assertIn("not shipped", logged.output[0], "the reason must reach the log")

    def test_a_mixed_report_logs_every_capability(self):
        with self.assertLogs(caps.log, level=logging.INFO) as logged:
            caps.log_capabilities((_ok("charts"), _bad("flags"), _ok("traces")))
        self.assertEqual(3, len(logged.output))


class RealBuildTest(unittest.TestCase):
    """Against this checkout everything should probe healthy - a smoke test for the probes
    themselves, and in CI a check that pyqtgraph/zstandard are still pinned in the manifest."""

    def test_this_checkout_is_not_degraded(self):
        for cap in caps.check_capabilities():
            with self.subTest(capability=cap.name):
                self.assertTrue(cap.ok, f"{cap.name}: {cap.detail} — {cap.consequence}")


if __name__ == "__main__":
    unittest.main()
