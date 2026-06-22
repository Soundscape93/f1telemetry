"""Integration test: replay real F1 telemetry captures and verify complete parsing.

This test reads actual .f1cap files (recordings of F1 2025/2026 telemetry), replays
them through the parser, and asserts that all packets are accounted for:
    total packets == parsed + skipped_unknown + skipped_malformed

If skipped > 0, the test fails — indicating either a bug in our structs/registry,
a corrupt capture, or a protocol change we haven't modeled yet.

The test is skipped if the capture file is not on disk, so it's optional but runs
by default if a capture is present.

Run::

    python -m unittest f1telemetry.test.integration_replay_tests
    python -m unittest f1telemetry.test.integration_replay_tests.ReplayIntegrationTest.test_replay_race_2026
"""

from __future__ import annotations

import os
import unittest

from f1telemetry.src.ingest.sources import FileReplaySource
from f1telemetry.src.protocol.parser import PacketParser
from f1telemetry.src.protocol.registry import build_registry


class ReplayIntegrationTest(unittest.TestCase):
    """Replay real captures and verify complete parsing with zero drops."""

    @staticmethod
    def _capture_path(filename: str) -> str:
        """Resolve capture file path relative to workspace root."""
        workspace_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return os.path.join(workspace_root, filename)

    def _replay_and_verify(self, capture_filename: str) -> None:
        """Replay a capture file and assert zero drops.
        
        Args:
            capture_filename: Filename relative to workspace root (e.g., "race_2026.f1cap").
        
        Raises:
            AssertionError if any packets were skipped.
        """
        capture_path = self._capture_path(capture_filename)
        registry = build_registry()
        parser = PacketParser(registry)
        
        source = FileReplaySource(capture_path, realtime=False)
        for raw_packet in source:
            parser.parse(raw_packet)
        
        total = parser.parsed + parser.skipped_unknown + parser.skipped_malformed
        
        self.assertEqual(
            parser.skipped_unknown, 0,
            f"{capture_filename}: {parser.skipped_unknown} unknown packets "
            "(unmodeled format/id or protocol change)"
        )
        self.assertEqual(
            parser.skipped_malformed, 0,
            f"{capture_filename}: {parser.skipped_malformed} malformed packets "
            "(truncation, size mismatch, or struct bug)"
        )
        self.assertGreater(
            parser.parsed, 0,
            f"{capture_filename}: no packets parsed (corrupt or empty capture)"
        )

    @unittest.skipIf(
        not os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "race_2026.f1cap"
        )),
        "race_2026.f1cap not found; skipping (optional integration test)"
    )
    def test_replay_race_2026(self) -> None:
        """Replay a 2026 race capture; all packets must parse with zero drops."""
        self._replay_and_verify("race_2026.f1cap")

    @unittest.skipIf(
        not os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "my_race.f1cap"
        )),
        "my_race.f1cap not found; skipping (optional integration test)"
    )
    def test_replay_my_race(self) -> None:
        """Replay my_race.f1cap capture; all packets must parse with zero drops."""
        self._replay_and_verify("my_race.f1cap")


if __name__ == "__main__":
    unittest.main()