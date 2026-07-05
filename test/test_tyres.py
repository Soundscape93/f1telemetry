from __future__ import annotations

import unittest

from f1telemetry.src.protocol.enums import VisualTyreCompound as V
from f1telemetry.src.ui.components.tyres import _COMPOUND_STYLE


class TyreStyleTest(unittest.TestCase):
    def test_f1_compound_letters(self):
        self.assertEqual(_COMPOUND_STYLE[V.SOFT][0], "S")
        self.assertEqual(_COMPOUND_STYLE[V.MEDIUM][0], "M")
        self.assertEqual(_COMPOUND_STYLE[V.HARD][0], "H")
        self.assertEqual(_COMPOUND_STYLE[V.INTER][0], "I")
        self.assertEqual(_COMPOUND_STYLE[V.WET][0], "W")

    def test_f2_super_soft_is_ss(self):
        self.assertEqual(_COMPOUND_STYLE[19][0], "SS")

    def test_each_style_is_letter_stripe_text(self):
        for compound, style in _COMPOUND_STYLE.items():
            self.assertEqual(len(style), 3, f"compound {compound} style must be (letter, stripe, text)")
            letter, stripe, text = style
            self.assertTrue(letter)
            self.assertTrue(stripe.startswith("#"))
            self.assertTrue(text.startswith("#"))


if __name__ == "__main__":
    unittest.main()
