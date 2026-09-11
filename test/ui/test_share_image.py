"""The share image's markup - every decision the renderer makes, asserted without a QApplication.

``render_document`` itself needs one (fonts, and the tyre icon is a ``QPixmap``), and the suite
never builds one: ``test_crash`` asserts behaviour that exists only while there is none, and every
module here runs in one process. So the paint is verified offscreen, and what is asserted here is
the string it paints from - which colour, which weight, what may wrap, what is escaped, and which
icons appear.
"""
import re
import unittest

from f1telemetry.src.ui.components.share_document import (
    Align,
    Cell,
    Column,
    Facts,
    Icon,
    IconKind,
    Notes,
    ShareDocument,
    Table,
    Tone,
)
from f1telemetry.src.ui.components.share_image import document_html
from f1telemetry.test.ui.test_share_document import standings_document

_SWISS = Icon(IconKind.FLAG, 79)
_UNMAPPED = Icon(IconKind.FLAG, 0)          # no nationality, so no bundled flag
_SOFT = Icon(IconKind.TYRE, 16)


def _html(*blocks, **fields) -> str:
    """One document's markup, with every icon it uses resolved unless ``icons`` says otherwise."""
    icons = fields.pop("icons", None)
    document = ShareDocument(title=fields.pop("title", "Shanghai — Sprint Race"), name="n",
                             blocks=blocks, **fields)
    return document_html(document, document.icons() if icons is None else icons)


def _cells(html: str) -> list[str]:
    """The contents of every table cell, in document order."""
    return re.findall(r"<td[^>]*>(.*?)</td>", html)


class ThemeTests(unittest.TestCase):
    """Nothing in the markup is left for the app's theme to decide."""

    def test_the_body_states_its_own_text_colour(self):
        """What a plain cell falls back to - and in a dark-themed app, the palette's text colour
        would otherwise be near-white on white paper."""
        self.assertIn('<body style="color:#1f2328;', _html())

    def test_each_tone_is_written_as_its_colour(self):
        tones = {Tone.MUTED: "#59636e", Tone.FASTEST: "#0969da", Tone.GAIN: "#1a7f37",
                 Tone.LOSS: "#cf222e"}
        for tone, colour in tones.items():
            with self.subTest(tone=tone):
                html = _html(Notes((Cell("1:35.435", tone=tone),)))
                self.assertIn(f'<span style="color:{colour}">1:35.435</span>', html)

    def test_a_plain_cell_carries_no_style_of_its_own(self):
        self.assertIn(">Max Verstappen</p>", _html(Notes((Cell("Max Verstappen"),))))

    def test_strong_is_weight_and_never_colour(self):
        """Bold means "a human car" or "a penalty that counts" - never a colour the theme could own."""
        self.assertIn('<span style="font-weight:600">Kevin Fust</span>',
                      _html(Notes((Cell("Kevin Fust", strong=True),))))

    def test_tone_and_weight_combine_on_one_cell(self):
        self.assertIn('<span style="color:#1a7f37; font-weight:600">▲</span>',
                      _html(Notes((Cell("▲", tone=Tone.GAIN, strong=True),))))


class EscapingTests(unittest.TestCase):
    """A captured online name is arbitrary text, and must not be read as markup."""

    def test_every_text_the_document_carries_is_escaped(self):
        name = '<b>Kev & "Co"</b>'
        html = _html(Facts(((name, Cell(name)),)),
                     Table((Column(name),), rows=((Cell(name),),), title=name, note=name),
                     Notes((Cell(name),), title=name),
                     title=name, meta=name, footer=name)
        self.assertNotIn("<b>", html)
        self.assertEqual(10, html.count('&lt;b&gt;Kev &amp; "Co"&lt;/b&gt;'))
        self.assertEqual(1, html.count('&lt;B&gt;KEV &amp; "CO"&lt;/B&gt;'))    # the fact's label


class IconTests(unittest.TestCase):
    """Only icons the renderer holds an image for are written."""

    def test_a_resolved_icon_sits_before_its_text(self):
        html = _html(Notes((Cell("soundscape93", icon=_SWISS),)))
        self.assertIn('<img src="flag/79" width="23" height="17" style="vertical-align:middle">'
                      "&nbsp;&nbsp;soundscape93", html)

    def test_an_unresolved_icon_is_left_out_and_its_text_kept(self):
        """Qt paints a broken-image placeholder for an ``<img>`` with no resource behind it."""
        html = _html(Notes((Cell("Car 14", icon=_UNMAPPED),)), icons=())
        self.assertNotIn("<img", html)
        self.assertIn(">Car 14</p>", html)

    def test_only_the_icons_handed_in_are_drawn(self):
        html = _html(Notes((Cell("a", icon=_SWISS), Cell("b", icon=_UNMAPPED))), icons={_SWISS})
        self.assertEqual(['flag/79'], re.findall(r'<img src="([^"]+)"', html))

    def test_a_tyre_is_drawn_at_the_pages_own_size(self):
        """22 px, as the session page draws it - smaller, and the Soft's red S stops reading."""
        cells = _cells(_html(Table((Column("TYRE", Align.CENTER),), rows=((Cell(icon=_SOFT),),))))
        self.assertEqual(['<img src="tyre/16" width="22" height="22" style="vertical-align:middle">'],
                         cells[1:])


class TableTests(unittest.TestCase):
    """How a table's rows and columns come out."""

    def test_no_cell_is_ever_empty(self):
        """A table whose last cell is empty swallows the next heading's top margin in Qt - found on
        a qualifying session whose last car had no grid penalty."""
        html = _html(Table((Column(""), Column("GRID PENALTY")),
                           rows=((Cell("1"), Cell("")),)), Notes((Cell("x"),), title="Race control"))
        self.assertIsNone(re.search(r"<td[^>]*></td>", html))
        self.assertEqual(["&nbsp;", "GRID PENALTY", "1", "&nbsp;"], _cells(html))

    def test_numbers_never_wrap_and_names_may(self):
        html = document_html(standings_document())
        driver_row = re.search(r"<tr><td[^>]*>1</td>.*?</tr>", html).group(0)
        tds = re.findall(r"<td[^>]*>", driver_row)
        self.assertIn("white-space:nowrap", tds[0])       # POS
        self.assertNotIn("white-space", tds[1])           # DRIVER
        self.assertIn("white-space:nowrap", tds[2])       # NO.
        self.assertIn("white-space:nowrap", tds[3])       # POINTS

    def test_columns_align_as_declared(self):
        tds = re.findall(r'<td align="(\w+)" valign', _html(Table(
            (Column("POS", Align.RIGHT), Column("DRIVER"), Column("TYRE", Align.CENTER)),
            rows=((Cell("1"), Cell("A"), Cell("S")),))))
        self.assertEqual(["right", "left", "center"], tds)

    def test_the_header_row_is_shaded_and_every_second_row_striped(self):
        rows = re.findall(r"<tr[^>]*>", _html(Table((Column("POS"),), rows=tuple(
            (Cell(str(n)),) for n in range(1, 5)))))
        self.assertEqual(['<tr bgcolor="#eaeef2">', "<tr>", '<tr bgcolor="#f6f8fa">', "<tr>",
                          '<tr bgcolor="#f6f8fa">'], rows)

    def test_a_title_and_its_note_come_before_the_table(self):
        html = _html(Table((Column("LAP"),), rows=((Cell("1"),),),
                           title="Race control · Penalties (11)",
                           note="1 counted towards the classification."))
        title = html.index("Race control · Penalties (11)")
        note = html.index("1 counted towards the classification.")
        self.assertLess(title, note)
        self.assertLess(note, html.index("<table"))


class LayoutTests(unittest.TestCase):
    """The rest of the page: facts, notes, the head and the foot."""

    def test_a_facts_label_reads_in_capitals_over_its_value(self):
        html = _html(Facts((("Fastest lap", Cell("Kevin Fust — 1:35.435", tone=Tone.FASTEST)),
                            ("Laps", Cell("10")))))
        self.assertEqual(
            ['<span style="font-size:13px; color:#59636e">FASTEST LAP</span><br>'
             '<span style="color:#0969da">Kevin Fust — 1:35.435</span>',
             '<span style="font-size:13px; color:#59636e">LAPS</span><br>10'], _cells(html))

    def test_facts_with_nothing_to_say_draw_no_table(self):
        self.assertNotIn("<table", _html(Facts(())))

    def test_every_note_line_is_its_own_paragraph(self):
        html = _html(Notes((Cell("Penalty detail hasn't been read yet.", tone=Tone.MUTED),
                            Cell("Max Verstappen — ⚑ ×1 (+5s)")), title="Race control · Penalties"))
        self.assertEqual(["Race control · Penalties",
                          '<span style="color:#59636e">Penalty detail hasn\'t been read yet.</span>',
                          "Max Verstappen — ⚑ ×1 (+5s)"],
                         re.findall(r"<p[^>]*>(.*?)</p>", html)[1:])

    def test_the_meta_line_is_muted_and_the_footer_sits_right(self):
        html = _html(meta="Season 1 · Round 2", footer="f1telemetry v0.11.0")
        self.assertIn('<p style="color:#59636e; margin-top:6px; margin-bottom:0">Season 1 · Round 2</p>',
                      html)
        self.assertIn('<p align="right" style="font-size:13px; color:#59636e; margin-top:24px">'
                      "f1telemetry v0.11.0</p>", html)

    def test_an_absent_meta_line_or_footer_leaves_no_empty_paragraph(self):
        self.assertEqual(1, _html().count("<p"))            # the title alone

    def test_a_standings_document_renders_both_of_its_tables(self):
        """The model's third target, through the same markup: a header and a row per standing."""
        document = standings_document()
        html = document_html(document, document.icons())
        self.assertEqual(2, html.count("<table"))
        self.assertEqual(1 + 6 + 1 + 4, html.count("<tr"))
        self.assertEqual(6, html.count("<img"))             # a flag in every driver's cell...
        self.assertEqual(5, len(set(re.findall(r'<img src="([^"]+)"', html))))   # ...two share one


if __name__ == "__main__":
    unittest.main()
