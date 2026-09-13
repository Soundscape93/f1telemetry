"""A whole weekend as a folder of ``ShareDocument``s - what the weekend page's Share exports (E19).
Qt-free, so the naming and the ordering are unit-tested the way ``session_share``'s strings are.

**N images, not one.** Eight sessions stacked into a single picture is about ten thousand pixels
tall and unreadable, and one file per session is what a league admin posts anyway - one message
each. So this is not a renderer: it calls ``session_share.session_document`` per session, exactly
as Session detail's Share does, and decides only what the set is called.

**The folder sorts in running order, because the file names do.** A weekend's sessions are already
in running order when they arrive here, but their recorded times are not always: a re-driven
session is recorded after the ones that follow it in the weekend. So each file is numbered from its
position, and the number is what a folder listing sorts by. The recorded time stays in the name
beside it, because that is what tells two attempts at one slot apart - the app numbers no attempt
(core invariant #5), and ``01_1159_Practice-2`` / ``02_1207_Practice-2`` name both without either
claiming to be the real one.

**Inside the folder the names are short.** The folder already says the date, the track and the
round, so repeating them nine times over would only make every name harder to read. A file lifted
out of the folder on its own still says which session it is, and the image itself carries the rest.

**It exports what the page shows, including an attempt nobody assigned.** The weekend page lists
the weekend's *stored* sessions rather than the round's assigned ones, deliberately, and an export
that quietly dropped the difference would be a second rule nothing on screen states.

**The standings come last**, as the round's own result does in the chat: here is the weekend, and
here is where it leaves the championship. Built by the caller (``components.standings_share``) and
handed in, because standings are a season's and this module knows only about one weekend.
"""
from __future__ import annotations

from dataclasses import replace
from typing import NamedTuple

from ...protocol.reference import track_name
from ..components.share_document import ShareDocument, file_stem
from ..formatting import recorded_label
from .session_share import session_document
from .weekend_view import SessionRow


class WeekendExport(NamedTuple):
    """A folder name and the documents that go in it, in the order they are numbered.

    A ``NamedTuple`` rather than a dataclass so it *is* a plain pair: ``ShareControl`` takes one
    without importing this module, which ``components/`` must not do (it may not import a surface).
    """

    folder: str
    documents: tuple[ShareDocument, ...]


def weekend_documents(rows, round_number: int, season_name: str, standings=None,
                      penalties_of=lambda session: (), name_of_for=None) -> WeekendExport:
    """One weekend as its folder of images: a file per session in running order, standings last.

    ``rows`` is the weekend page's own rows (``weekend_view.weekend_rows``); the ``SlotRow``s in it
    are positions holding no session, so there is nothing to export for them. ``round_number`` and
    ``season_name`` place every image the way Session detail's Share places one - the season already
    named as ``components.season_phrase`` names it, since this module is Qt-free. ``penalties_of``
    and ``name_of_for`` are asked per session for its stored ``PENA`` rows and for the resolver the
    page names its drivers with. ``standings`` is the championship as of this round, or None.
    """
    sessions = [row for row in rows if isinstance(row, SessionRow)]
    namer = name_of_for or (lambda session: (lambda entry: entry.driver_name))
    documents = [
        replace(session_document(row.session, row.slot, penalties_of(row.session),
                                 namer(row.session), (season_name, round_number)),
                name=file_stem(_index(position), _at(row.session), row.label))
        for position, row in enumerate(sessions, start=1)]
    if standings is not None:
        # The same phrase ``standings_share`` names its own file with, shortened the way the
        # session names are: the folder already says which round this is.
        documents.append(replace(standings, name=file_stem(
            _index(len(documents) + 1), f"Standings round {round_number}")))
    return WeekendExport(_folder(sessions, round_number), tuple(documents))


def _folder(sessions, round_number: int) -> str:
    """``2026-07-05_Shanghai_Round-2`` - date-led, so a folder of exports sorts chronologically.

    Named from what is in it, so a round holding nothing is still named rather than left blank.
    The date is the earliest session's, which is the day the weekend was driven; a session stored
    without a recorded time simply does not contribute one.
    """
    track = track_name(sessions[0].session.track_id) if sessions else ""
    return file_stem(_date(sessions), track, f"Round {round_number}")


def _date(sessions) -> str:
    """The day the weekend started, as ``recorded_label`` renders it, or "" if none is stored."""
    stamps = [_at(row.session, part=0) for row in sessions]
    return min((stamp for stamp in stamps if stamp), default="")


def _at(session, part: int = -1) -> str:
    """A session's recorded date (``part=0``) or its time without the colon (``part=-1``).

    Through ``recorded_label`` rather than ``strftime``, so a file name and the line the page shows
    are the same moment: it is the one place that converts a stored UTC stamp to local time.
    """
    if session.recorded_at is None:
        return ""
    return recorded_label(session.recorded_at).replace(":", "").split()[part]


def _index(position: int) -> str:
    """``01``, ``02``, ... - two digits, so a listing sorts them in the order they were driven."""
    return f"{position:02d}"
