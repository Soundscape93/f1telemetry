from __future__ import annotations

import unittest

from f1telemetry.src.protocol.reference import NATIONALITY_NAMES
from f1telemetry.src.ui.components.flags import _FLAGS_DIR, _NATIONALITY_FLAG, flag_code


class FlagMappingTest(unittest.TestCase):
    def test_every_nationality_has_a_flag_code(self):
        unmapped = [nid for nid in NATIONALITY_NAMES if nid not in _NATIONALITY_FLAG]
        self.assertEqual(unmapped, [], f"nationalities without a flag code: {unmapped}")

    def test_every_flag_code_has_a_bundled_asset(self):
        missing = sorted(
            code for code in set(_NATIONALITY_FLAG.values())
            if not (_FLAGS_DIR / f"{code}.svg").exists()
        )
        self.assertEqual(missing, [], f"flag codes without an SVG asset: {missing}")

    def test_flag_code_lookup(self):
        self.assertEqual(flag_code(10), "gb")       # British
        self.assertEqual(flag_code(24), "gb-eng")   # English -> home nation flag
        self.assertEqual(flag_code(53), "mc")       # Monegasque -> Monaco
        self.assertIsNone(flag_code(9999))          # unknown id -> no flag


if __name__ == "__main__":
    unittest.main()
