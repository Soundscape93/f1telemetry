"""The shareable document and its file names - the surface-neutral half of E19, without Qt.

One session is the only document shipped with this, and the weekend and the standings come next.
The standings are not exported yet, so the test that matters most here builds a standings-shaped
document out of the real ``StandingRow`` and ``ConstructorRow``: the proof that the *model*, and
not only the session builder, can say what the season page shows.

The standings fixture is this database's own league - Mittwoch League after round 3, as
``league_standings_for_rounds`` and ``constructor_standings_for_rounds`` computed it.
"""
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from f1telemetry.src.analysis.standings import ConstructorRow, StandingRow
from f1telemetry.src.protocol.reference import team_display_name
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
    file_stem,
    unique_path,
)

# Mittwoch League after round 3. soundscape93 and rolandmeier8302 are both Swiss, so one flag serves
# two rows.
_DRIVERS = (
    StandingRow(position=1, driver_name="patrickstein12", race_number=2, points=65, nationality_id=31),
    StandingRow(position=2, driver_name="remoriginal69", race_number=97, points=51, nationality_id=65),
    StandingRow(position=3, driver_name="soundscape93", race_number=50, points=49, nationality_id=79),
    StandingRow(position=4, driver_name="Fabibyte", race_number=11, points=45, nationality_id=41),
    StandingRow(position=5, driver_name="rolandmeier8302", race_number=24, points=24, nationality_id=79),
    StandingRow(position=6, driver_name="Sergio Perez", race_number=11, points=16, nationality_id=52),
)
_CONSTRUCTORS = (
    ConstructorRow(position=1, team_id=478, points=116),       # Red Bull Racing
    ConstructorRow(position=2, team_id=477, points=94),        # Ferrari
    ConstructorRow(position=3, team_id=486, points=25),        # Cadillac
    ConstructorRow(position=4, team_id=485, points=24),        # Audi
)


def standings_document(drivers=_DRIVERS, constructors=_CONSTRUCTORS) -> ShareDocument:
    """A championship as a later export is expected to build it - here only to prove the model can.

    The columns are the season page's own (``Pos / Driver / No. / Points`` and ``Pos / Team /
    Points``). Shared with ``test_share_image`` so the renderer's markup is asserted on this same
    document.
    """
    driver_table = Table(
        title="Drivers",
        columns=(Column("POS", Align.RIGHT), Column("DRIVER", wrap=True),
                 Column("NO.", Align.RIGHT), Column("POINTS", Align.RIGHT)),
        rows=tuple((Cell(str(row.position)),
                    Cell(row.driver_name, icon=Icon(IconKind.FLAG, row.nationality_id)),
                    Cell(str(row.race_number)),
                    Cell(str(row.points), strong=True)) for row in drivers))
    constructor_table = Table(
        title="Constructors",
        columns=(Column("POS", Align.RIGHT), Column("TEAM", wrap=True),
                 Column("POINTS", Align.RIGHT)),
        rows=tuple((Cell(str(row.position)), Cell(team_display_name(row.team_id)),
                    Cell(str(row.points), strong=True)) for row in constructors))
    return ShareDocument(
        title="Mittwoch League — standings after round 3",
        name=file_stem("Season 1", "Standings after round 3"),
        meta="Season 1 (“Mittwoch League”)  ·  3 of 24 rounds",
        blocks=(driver_table, constructor_table),
        footer="f1telemetry")


class TableTests(unittest.TestCase):
    """A table refuses a row that would put a value in the wrong column."""

    _COLUMNS = (Column("POS", Align.RIGHT), Column("DRIVER"), Column("PTS", Align.RIGHT))

    def test_a_row_missing_a_cell_is_refused(self):
        """Drawn, it would shift the points into the driver column and read as a wrong result."""
        with self.assertRaisesRegex(ValueError, "row 1 has 2 cells for 3 columns"):
            Table(self._COLUMNS, rows=((Cell("1"), Cell("A"), Cell("25")),
                                       (Cell("2"), Cell("B"))))

    def test_a_row_with_a_cell_too_many_is_refused(self):
        with self.assertRaisesRegex(ValueError, "row 0 has 4 cells for 3 columns"):
            Table(self._COLUMNS, rows=((Cell("1"), Cell("A"), Cell("25"), Cell("x")),))

    def test_a_table_with_no_rows_is_allowed(self):
        """A heading over nothing is a real state - an empty field - not a malformed table."""
        self.assertEqual((), Table(self._COLUMNS).rows)

    def test_a_cell_is_plain_unemphasised_text_unless_told_otherwise(self):
        self.assertEqual(Cell("Max Verstappen"),
                         Cell("Max Verstappen", tone=Tone.PLAIN, strong=False, icon=None))

    def test_the_document_cannot_be_changed_after_it_is_built(self):
        """Frozen like every value object here: what was built is what gets drawn and saved."""
        document = standings_document()
        with self.assertRaises(FrozenInstanceError):
            document.title = "something else"


class IconTests(unittest.TestCase):
    """What the renderer is asked to resolve."""

    def test_every_icon_is_listed_once_in_the_order_it_is_first_used(self):
        """Across all three kinds of block, with a repeat in each, so no kind is skipped."""
        swiss, italian, soft = Icon(IconKind.FLAG, 79), Icon(IconKind.FLAG, 41), Icon(IconKind.TYRE, 16)
        document = ShareDocument(title="t", name="n", blocks=(
            Facts((("Fastest lap", Cell("soundscape93", icon=swiss)),)),
            Table((Column("DRIVER"), Column("TYRE")), rows=(
                (Cell("soundscape93", icon=swiss), Cell(icon=soft)),
                (Cell("Fabibyte", icon=italian), Cell(icon=soft)))),
            Notes((Cell("Fabibyte", icon=italian), Cell("no icon"))),
        ))
        self.assertEqual((swiss, soft, italian), document.icons())

    def test_a_document_without_icons_asks_for_none(self):
        self.assertEqual((), ShareDocument(title="t", name="n",
                                           blocks=(Notes((Cell("text"),)),)).icons())


class StandingsShapeTests(unittest.TestCase):
    """A standings table, built from the real standings rows, is something the model can say."""

    def test_the_driver_table_carries_every_row_with_its_flag(self):
        drivers = standings_document().blocks[0]
        self.assertEqual(["POS", "DRIVER", "NO.", "POINTS"], [c.header for c in drivers.columns])
        self.assertEqual(
            [("1", "patrickstein12", "2", "65"), ("2", "remoriginal69", "97", "51"),
             ("3", "soundscape93", "50", "49"), ("4", "Fabibyte", "11", "45"),
             ("5", "rolandmeier8302", "24", "24"), ("6", "Sergio Perez", "11", "16")],
            [tuple(cell.text for cell in row) for row in drivers.rows])
        self.assertEqual([31, 65, 79, 41, 79, 52], [row[1].icon.key for row in drivers.rows])

    def test_the_constructor_table_names_teams_the_way_the_page_does(self):
        """``team_display_name``, so "Ferrari '26" reads "Ferrari" here as it does on screen."""
        constructors = standings_document().blocks[1]
        self.assertEqual(["POS", "TEAM", "POINTS"], [c.header for c in constructors.columns])
        self.assertEqual(
            [("1", "Red Bull Racing", "116"), ("2", "Ferrari", "94"), ("3", "Cadillac", "25"),
             ("4", "Audi", "24")],
            [tuple(cell.text for cell in row) for row in constructors.rows])

    def test_numbers_sit_right_and_names_may_wrap(self):
        for table in standings_document().blocks:
            with self.subTest(table=table.title):
                self.assertEqual(Align.RIGHT, table.columns[0].align)
                self.assertEqual(Align.RIGHT, table.columns[-1].align)
                self.assertTrue(table.columns[1].wrap)
                self.assertFalse(table.columns[-1].wrap)

    def test_one_flag_serves_every_driver_of_a_nationality(self):
        """Two Swiss drivers, one Swiss flag to resolve."""
        self.assertEqual([31, 65, 79, 41, 52], [icon.key for icon in standings_document().icons()])


class FileStemTests(unittest.TestCase):
    """The name a document is saved under."""

    def test_a_session_reads_date_time_track_and_slot(self):
        self.assertEqual("2026-07-05_1246_Shanghai_Sprint-Race",
                         file_stem("2026-07-05", "1246", "Shanghai", "Sprint Race"))

    def test_characters_windows_refuses_become_separators(self):
        """Replaced rather than dropped, so two words never run together. Brackets are legal."""
        self.assertEqual("Sakhir-(Bahrain)", file_stem("Sakhir (Bahrain)"))
        self.assertEqual("a-b-c-d-e-f-g-h-i-j", file_stem('a<b>c:d"e/f\\g|h?i*j'))
        self.assertEqual("tab-new-line", file_stem("tab\tnew\nline"))

    def test_an_underscore_is_only_ever_a_join(self):
        """One inside a part would make the join ambiguous, so it becomes a dash like a space."""
        self.assertEqual("Kevin-Fust_Race", file_stem("Kevin_Fust", "Race"))

    def test_a_part_left_empty_is_dropped_rather_than_doubling_the_join(self):
        self.assertEqual("Shanghai_Race", file_stem("", "Shanghai", "  ", "...", "Race"))

    def test_leading_and_trailing_dots_and_dashes_go(self):
        """Windows strips a trailing dot on its own and would save a different name."""
        self.assertEqual("Race_Qualifying", file_stem("Race.", "-Qualifying-"))

    def test_letters_outside_ascii_are_kept(self):
        self.assertEqual("São-Paulo_Race", file_stem("São Paulo", "Race"))


class UniquePathTests(unittest.TestCase):
    """A save can never land on a file that is already there."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_the_first_save_takes_the_plain_name(self):
        self.assertEqual(self.folder / "2026-07-05_1246_Shanghai_Sprint-Race.png",
                         unique_path(self.folder, "2026-07-05_1246_Shanghai_Sprint-Race"))

    def test_each_later_save_is_offered_a_new_name_and_the_first_file_is_untouched(self):
        first = unique_path(self.folder, "Shanghai_Race")
        first.write_bytes(b"first")
        second = unique_path(self.folder, "Shanghai_Race")
        second.write_bytes(b"second")
        third = unique_path(self.folder, "Shanghai_Race")
        self.assertEqual(["Shanghai_Race.png", "Shanghai_Race-2.png", "Shanghai_Race-3.png"],
                         [first.name, second.name, third.name])
        self.assertEqual(b"first", first.read_bytes())

    def test_a_folder_is_named_the_same_way(self):
        """``suffix=""`` - an export of several files gets a fresh folder of its own."""
        folder = unique_path(self.folder, "2026-07-03_Shanghai", suffix="")
        self.assertEqual(self.folder / "2026-07-03_Shanghai", folder)
        folder.mkdir()
        self.assertEqual(self.folder / "2026-07-03_Shanghai-2",
                         unique_path(self.folder, "2026-07-03_Shanghai", suffix=""))

    def test_numbered_files_sort_in_the_order_they_were_numbered(self):
        """A sprint weekend is nine sessions plus standings - ten files - so two digits, or "10_"
        would sort before "2_"."""
        stems = [f"{index:02d}" for index in range(1, 11)]
        names = [file_stem(stem, "Shanghai") for stem in stems]
        self.assertEqual(names, sorted(names))


if __name__ == "__main__":
    unittest.main()
