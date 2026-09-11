"""What an exported image says, before anything draws it - Qt-free, so every string it carries is
unit-testable the way ``race_control`` is (DECISIONS -> UI, E19).

A result reaches the league chat as a PNG the app lays out itself, not as a screenshot of its own
widgets. This module is the half of that which decides *content*: a document - a title, a meta
line, a run of blocks and a footer - that a surface's builder fills in and ``share_image`` paints.
It knows nothing about sessions, standings or Qt.

**Surface-neutral on purpose.** The first document is one session, built on the Sessions surface
(``sessions/session_share.py``). A whole weekend and the standings as of a round come next, and
the standings are wanted from the season page as well as from the weekend page. Seasons pages must
not import from ``sessions/`` and this package must not import a surface, so the model, the
renderer and the delivery live here, and only the builders live with their data.

**Three kinds of block cover every target so far.** A classification, a race-control list and a
standings table are all a ``Table``; a session's header facts are ``Facts``; the race-control box's
two states that have no rows are ``Notes``. A new kind of block is a renderer change, so none is
added before a document needs one.

**A cell carries meaning, not colour.** Emphasis is two independent axes, because that is how the
session page already uses it: ``tone`` is colour (the fastest lap, places gained or lost, an
estimate) and ``strong`` is weight (a human rather than an AI car, a penalty the classification
counts). The renderer owns the palette - one fixed light palette, whatever the app's theme - so
nothing here can carry a theme into a file. Icons are references for the same reason: a nationality
or a compound id, which the renderer resolves to an image, so this module never holds one.

**The file-name convention lives here too**, because it is a string decision like the others and
more than one surface will write files. ``file_stem`` makes the parts safe and joins them, and
``unique_path`` never hands back a name that already exists. One session is one file; a weekend
will be one fresh folder holding a file per session, numbered so the folder sorts in running order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Align(Enum):
    """Where a column's cell sit - numbers right and names left, the way the page's tables read."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class Tone(Enum):
    """What a cell's colour means. The renderer maps each to a colour that reads on white.
    
    The app's own vocabulary (``ui/style``) and no more: a fastest lap has to look like a fastest
    lap wherever it is shown, or the colour stops meaning anything.
    """

    PLAIN = "plain"
    MUTED = "muted"             # context rather than result: an estimate, a note
    FASTEST = "fastest"         # the session's fastest lap - style.FASTEST_LAP on screen
    GAIN = "gain"               # places gained - style.POSITION_GAIN
    LOSS = "loss"               # places lost - style.POSITION_LOSS


class IconKind(Enum):
    """Which bundled picture an ``Icon``'s key names."""

    FLAG = "flag"               # key: a nationality id, as ``components.flags`` maps it
    TYRE = "tyre"               # key: a visual compound id, as ``components.tyres`` draws it


@dataclass(frozen=True)
class Icon:
    """A picture in a cell, by reference.
    
    One the renderer cannot resolve - a nationality with no bundled flag - is left out, excactly as
    the page leaves the flag out of its cell.
    """

    kind: IconKind
    key: int


@dataclass(frozen=True)
class Cell:
    """One value: its text, what its colour means, whether it is bold, and an icon before it."""

    text: str = ""
    tone: Tone = Tone.PLAIN
    strong: bool = False
    icon: Icon | None = None


@dataclass(frozen=True)
class Column:
    """A table column's header and how its cells behave.

    ``wrap`` is what keeps a document from being cut off at the image's fixed width: a column of
    names or reasons may break onto a second line, and a column of numbers never does. A name
    column has to be allowed to - the game's ``m_name`` is 32 bytes, so a name can be 31
    characters with no space to break at.
    """

    header: str
    align: Align = Align.LEFT
    wrap: bool = False


@dataclass(frozen=True)
class Table:
    """Rows of cells under a header, with an optional title and a muted note beneath the title.

    A row that does not have one cell per column is refused here rather than drawn: a missing cell
    moves every value after it into the wrong column, which reads as a wrong result rather than as
    a fault.
    """

    columns: tuple[Column, ...]
    rows: tuple[tuple[Cell, ...], ...] = ()
    title: str = ""
    note: str = ""

    def __post_init__(self):
        for index, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(
                    f"row {index} has {len(row)} cells for {len(self.columns)} columns")


@dataclass(frozen=True)
class Facts:
    """Labelled values read across one line - a session's fastest lap, its weather, and so on."""

    pairs: tuple[tuple[str, Cell], ...]
    title: str = ""


@dataclass(frozen=True)
class Notes:
    """Lines of text under an optional title, for whatever is not a table."""
    
    lines: tuple[Cell, ...]
    title: str = ""


Block = Facts | Table | Notes


@dataclass(frozen=True)
class ShareDocument:
    """One image's worth of content, top to bottom.

    ``name`` is the file stem the document saves under, decided by whoever built it, because only
    the builder knows what identifies the content - for a session that includes its recorded time,
    the one thing that tells two attempts at a slot apart (core invariant #5).
    """

    title: str
    name: str
    meta: str = ""
    blocks: tuple[Block, ...] = ()
    footer: str = ""

    def icons(self) -> tuple[Icon, ...]:
        """Every distinct icon the document uses, in first-use order - what the renderer resolves."""
        seen: dict[Icon, None] = {}
        for block in self.blocks:
            for cell in _cells(block):
                if cell.icon is not None:
                    seen.setdefault(cell.icon, None)
        return tuple(seen)


def _cells(block: Block) -> tuple[Cell, ...]:
    """Every cell in one block, whatever its kind."""
    if isinstance(block, Table):
        return tuple(cell for row in block.rows for cell in row)
    if isinstance(block, Facts):
        return tuple(cell for _, cell in block.pairs)
    return block.lines


# --- file names ------–-------------------------------------------------------------------------------

# What Windows refuses in a file name, plus the control range. Replaced by a separater rather than
# dropped, so "Sakhir/Bahrain" cannot run its two words together.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SEPARATORS = re.compile(r"[\s_]+")


def file_stem(*parts: str) -> str:
    """A file or folder name without its suffix: each part made safe, then the parts joined by ``_``.

    Inside a part, spaces and underscores become ``-``, so an underscore in the result is always a
    join - ``2026-07-05_1246_Shanghai_Sprint-Race``. A part left empty by cleaning is dropped
    rather than leaving ``__`` behind. Leading and trailing dots and dashes go too, since Windows
    silently strips a trailing dot and would write a different name from the one asked for.
    """
    cleaned = (_SEPARATORS.sub("-", _UNSAFE.sub(" ", part).strip()).strip(".-") for part in parts)
    return "_".join(part for part in cleaned if part)


def unique_path(folder: Path, stem: str, suffix: str = ".png") -> Path:
    """``folder/stem`` + ``suffix``, or the first of ``stem-2``, ``stem-3``, ... not taken yet.

    This is what keeps a second save from overwriting the first without asking: the name offered
    is always free, so replacing a file takes choosing it in the save dialog, which then asks.
    ``suffix=""`` names a folder instead, for an export that writes several files into a fresh one.
    """
    candidate = folder / f"{stem}{suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{number}{suffix}"
        number += 1
    return candidate
