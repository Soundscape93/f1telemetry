"""The font helpers that replaced font-only stylesheets, and the guard that keeps them out
(PRIORITIES -> A4).

Qt-free like every suite here: ``QFont`` needs no ``QApplication``, and the helpers only ever touch
``font()`` / ``setFont()``, so a two-line stub stands in for the widget.

Three silent failure modes are pinned down here because each one *looks* right in review: px
quietly becoming pt (which resizes text on HiDPI panels), weight 600 quietly becoming 700
(``setBold(True)``), and an inherited family being dropped by building a fresh ``QFont`` instead of
mutating the widget's own.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from PySide6.QtGui import QFont

from f1telemetry.src.ui.style import (
    FASTEST_LAP_QSS,
    HEADING_WEIGHT,
    MUTED_TEXT_QSS,
    apply_bold,
    apply_font,
    apply_heading,
)

_UI_ROOT = Path(__file__).resolve().parents[2] / "src" / "ui"      # test/ui/ -> repo root


class _StubWidget:
    """The entire surface the helpers use: ``font()`` and ``setFont()``."""

    def __init__(self, font: QFont | None = None) -> None:
        self._font = QFont() if font is None else font

    def font(self) -> QFont:
        return QFont(self._font)        # QWidget.font() hands back a copy; so does this

    def setFont(self, font: QFont) -> None:
        self._font = font


class SizeTest(unittest.TestCase):
    def test_size_px_sets_pixel_size_and_never_a_point_size(self):
        widget = _StubWidget()
        apply_font(widget, size_px=20)
        self.assertEqual(20, widget.font().pixelSize())
        self.assertEqual(-1, widget.font().pointSize())

    def test_heading_sizes_in_pixels(self):
        widget = _StubWidget()
        apply_heading(widget, size_px=18)
        self.assertEqual(18, widget.font().pixelSize())
        self.assertEqual(-1, widget.font().pointSize())

    def test_non_positive_size_is_an_error(self):
        """setPixelSize(0) yields an invalid font and only warns at runtime."""
        for size in (0, -1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                apply_font(_StubWidget(), size_px=size)

    def test_there_is_no_point_size_argument(self):
        """A4 standardised on px; a pt path is how two scales drift apart again."""
        with self.assertRaises(TypeError):
            apply_font(_StubWidget(), size_pt=14)
        with self.assertRaises(TypeError):
            apply_heading(_StubWidget(), size_pt=14)


class WeightTest(unittest.TestCase):
    def test_heading_weight_is_600_and_bold_would_have_been_700(self):
        """The regression this guards: setBold(True) thickens every heading in the app."""
        self.assertEqual(600, int(HEADING_WEIGHT))
        self.assertEqual(700, int(QFont.Weight.Bold))

    def test_apply_heading_sets_exactly_600(self):
        widget = _StubWidget()
        apply_heading(widget, size_px=20)
        self.assertEqual(600, int(widget.font().weight()))

    def test_apply_bold_sets_600_without_touching_the_size(self):
        base = QFont()
        base.setPixelSize(13)
        widget = _StubWidget(base)
        apply_bold(widget)
        self.assertEqual(600, int(widget.font().weight()))
        self.assertEqual(13, widget.font().pixelSize())


class PreservationTest(unittest.TestCase):
    def test_existing_family_survives(self):
        widget = _StubWidget(QFont("DejaVu Sans"))
        apply_heading(widget, size_px=18)
        self.assertEqual("DejaVu Sans", widget.font().family())

    def test_attributes_not_asked_for_are_left_alone(self):
        base = QFont("DejaVu Sans")
        base.setItalic(True)
        widget = _StubWidget(base)
        apply_bold(widget)
        self.assertTrue(widget.font().italic())
        self.assertEqual("DejaVu Sans", widget.font().family())


# --- the A4 gate ----------------------------------------------------------------------------

_FONT_PROP = re.compile(r"\bfont(-size|-weight|-family|-style|-variant)?\s*:")
_SETS_COLOUR = re.compile(r"(?:^|[;{\s])color\s*:")
_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PT_SIZING = re.compile(r"setPointSize[F]?\s*\(")

# The one deliberate point size in the UI: QGraphicsSimpleTextItem inside the car-status scene,
# whose text is transformed with the view rather than laid out in device pixels. Not a styled
# widget label, so A4's px standard does not reach it. Drop this if it ever becomes one.
_PT_EXEMPT = frozenset({"components/car_status_graphic.py"})


# Cross-module constants a stylesheet may be built from. Constants defined in the file being
# scanned are picked up automatically by _module_constants, so only imported ones belong here.
_CONSTS = {
    "MUTED_TEXT_QSS": MUTED_TEXT_QSS,
    "style.MUTED_TEXT_QSS": MUTED_TEXT_QSS,
    "FASTEST_LAP_QSS": FASTEST_LAP_QSS,
    "style.FASTEST_LAP_QSS": FASTEST_LAP_QSS,
}


# Empty since A4b removed the last two font-bearing widget stylesheets. Kept as the documented
# escape hatch: add a (file, sheet) pair here only with a reason, and note that the stale-entry
# assertion below fails once that site is fixed, so an entry cannot quietly outlive its cause.
_DEFERRED: frozenset[tuple[str, str]] = frozenset()


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """``_CONSTS`` plus the module's own top-level ``NAME = "..."`` strings.

    Read from the source rather than listed here on purpose: a stylesheet built from a local colour
    constant (``f"background: {_BACKGROUND}"``) must stay checkable without copying that colour
    into this test, where it would silently go stale the first time the colour changes.
    """
    consts = dict(_CONSTS)
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            consts[node.targets[0].id] = node.value.value
    return consts


def _stylesheet_literal(node: ast.AST, consts: dict[str, str]) -> str | None:
    """The stylesheet argument as text, or None if it cannot be resolved statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Attribute):
        return consts.get(ast.unparse(node))
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = consts.get(ast.unparse(value.value))
                if resolved is None:
                    return None
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    return None


def _stylesheet_calls():
    """Every ``setStyleSheet`` under src/ui as (relative path, line, resolved text or None)."""
    for path in sorted(_UI_ROOT.rglob("*.py")):
        rel = path.relative_to(_UI_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet"
                    and node.args):
                yield rel, node.lineno, _stylesheet_literal(node.args[0], consts)


class NoFontStyleSheetsTest(unittest.TestCase):
    """A stylesheet that carries a font property must also set a colour.

    A4 was never one bad label - it was 33 stylesheets accumulated one reasonable-looking line at a
    time, each freezing the theme's text colour into its widget. A convention nobody can see is one
    that comes back, so this reads the source rather than trusting review: any sheet with a
    ``font-*`` property but no explicit ``color:`` fails, and the fix is the ``style.py`` helpers.

    Sheets that *do* set a colour are deliberate and fine (``MUTED_TEXT_QSS``): the cached palette
    never reaches their text.
    """

    def test_no_font_stylesheet_without_an_explicit_colour(self):
        offenders, seen_deferred = [], set()
        for rel, line, sheet in _stylesheet_calls():
            if sheet is None or not _FONT_PROP.search(sheet):
                continue
            key = (rel, " ".join(sheet.split()))
            if key in _DEFERRED:
                seen_deferred.add(key)
            elif not _SETS_COLOUR.search(sheet):
                offenders.append(f"{rel}:{line}  {sheet!r}")

        self.assertEqual([], offenders,
                         "font styling belongs in QFont, not a stylesheet - use style.apply_font / "
                         "apply_heading / apply_bold. A stylesheet freezes the theme's text colour "
                         "into the widget (PRIORITIES -> A4). Offenders:\n  "
                         + "\n  ".join(offenders))
        self.assertEqual(set(), _DEFERRED - seen_deferred,
                         "stale _DEFERRED entry: that site is fixed, so drop it from the allowlist")

    def test_every_stylesheet_can_be_read_statically(self):
        """A stylesheet built at runtime is exactly where this bug hides from review."""
        dynamic = [f"{rel}:{line}" for rel, line, sheet in _stylesheet_calls() if sheet is None]
        self.assertEqual([], dynamic,
                         "this stylesheet cannot be checked for a frozen text colour; set its "
                         f"color: explicitly, or add its constant to _CONSTS: {dynamic}")

    def test_no_stylesheet_is_a_bare_identifier(self):
        """``setStyleSheet("MUTED_TEXT_QSS")`` - the quoted constant name - applies nothing.

        A real bug found in slider_row.py during the A4 measurement: the min/max labels had never
        been muted. It is invisible in review and silent at runtime, so it gets a gate.
        """
        quoted = [f"{rel}:{line}  {sheet!r}" for rel, line, sheet in _stylesheet_calls()
                  if sheet is not None and _BARE_IDENTIFIER.match(sheet.strip())]
        self.assertEqual([], quoted,
                         f"this looks like a constant that was quoted by mistake: {quoted}")

    def test_text_is_sized_in_pixels_not_points(self):
        """A4 standardised the UI on px; mixing units is how the Help title drifted 25% large."""
        offenders, seen_exempt = [], set()
        for path in sorted(_UI_ROOT.rglob("*.py")):
            rel = path.relative_to(_UI_ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            if not _PT_SIZING.search(source) and "pt;" not in source:
                continue
            if rel in _PT_EXEMPT:
                seen_exempt.add(rel)
            else:
                offenders.append(rel)

        self.assertEqual([], offenders,
                         "size text in pixels via style.apply_font / apply_heading - the UI scale "
                         f"is 20/18/14/11 px (PRIORITIES -> A4). Offenders: {offenders}")
        self.assertEqual(set(), _PT_EXEMPT - seen_exempt,
                         "stale _PT_EXEMPT entry: that file no longer uses point sizing")


if __name__ == "__main__":
    unittest.main()
