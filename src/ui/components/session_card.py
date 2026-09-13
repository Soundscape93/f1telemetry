"""The one session card both Sessions overviews build.

A foldable card: a title that opens the session on a double-click, optional actions beside it, a
muted recorded-time / driver-count line on the right, and - unfolded - a compact summary row
(session, winner, fastest lap, weather, AI difficulty).

Shared as a *widget*, not as a base class. The two overviews differ in chrome, not in what a card
says, so the drift worth guarding against lives here and in ``sessions/weekend_view`` - what a card
says, and which rows exist - rather than in a page's layout (DECISIONS -> UI). What differs per
page is passed in: the ``title`` (the plain overview prefixes the track; the weekend page already
has it in the header), the ``actions``, and whether it opens ``expanded``.

The card never owns the fold *state*: it emits ``toggled`` and the page remembers, because the two
pages remember opposite things - the plain overview which cards were opened, the weekend page
which were closed.

Follows A4b like every other card in the app: no font-bearing stylesheet, ``apply_bold`` and
``MUTED_TEXT_QSS`` only (core invariant #11).
"""
from __future__ import annotations

from functools import partial
from typing import Callable, NamedTuple, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..formatting import recorded_label, session_fastest_lap, session_leader
from ..style import MUTED_TEXT_QSS, apply_bold
from .weather import WeatherIcon, session_weather


class CardAction(NamedTuple):
    """A small button beside the card's title: its text, its tooltip, and what it does.
    
    A sequence rather than a fixed ``on_delete``: both pages pass one Delete today, and the
    session-centric assignment branch adds Unassign to the weekend page's without touching this file.
    """

    text: str
    tooltip: str
    callback: Callable[[], None]


class _TitleButton(QToolButton):
    """The card's fold/unfold title, which also opens the session on a double-click."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        """Open the session, undoing the fold the first click of the pair already caused.

        A checkable button toggles on the first press/release of a double-click, well before the
        double-click event arrives - so the card would fold or unfold on its way to opening the
        session. Toggling back restores the state the user actually left it in, and ``toggled``
        fires again, so the page's fold bookkeeping stays correct with no extra work. Exactly one
        stray toggle needs undoing: the *second* release lands with the button no longer 'down',
        so ``QAbstractButton`` ignores it.
        """
        super().mouseDoubleClickEvent(event)
        self.setChecked(not self.isChecked())
        self.double_clicked.emit()


class SessionCard(QFrame):
    """One session: a title line always, the summary row when unfolded."""

    activated = Signal()        # the title was double-clicked, open the session
    toggled = Signal(bool)     # fold/unfold, so the page can remember

    def __init__(self, session, *, title: str, label: str,
                 name_of=lambda entry: entry.driver_name, note: str = "",
                 actions: Sequence[CardAction] = (), expanded: bool = False,
                 parent=None) -> None:
        """Build the card. ``label`` is the slot label the summary row's "Session" field shows,
        which is not always the "title" - the plain overview's title also carries the track.
        
        ``note`` is a muted aside beside the title, for something true of this card *on this page*
        rather than of the session: the weekend page marks the rows it has not assigned to the
        round it is showing. Empty on the plain overview, where every card means the same thing.
        """
        super().__init__(parent)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self._toggle = _TitleButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setText(title)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        # No stylesheet: it would freeze the button's text colour at apply time (A4b).
        self._toggle.setAutoRaise(True)
        apply_bold(self._toggle)
        self._toggle.setMinimumHeight(self._toggle.sizeHint().height() + 4)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setToolTip("Click to fold, double-click to open the session")
        self._toggle.double_clicked.connect(self.activated.emit)
        header.addWidget(self._toggle)

        if note:
            header.addWidget(_muted(note))

        for action in actions:
            button = QToolButton()
            button.setText(action.text)
            button.setAutoRaise(True)       # sits beside the title, so it must not shout
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(action.tooltip)
            button.clicked.connect(lambda _checked=False, run=action.callback: run())
            header.addWidget(button)

        header.addStretch(1)
        header.addWidget(_meta_label(session))
        vbox.addLayout(header)

        body = _summary_row(session, label, name_of)
        body.setVisible(expanded)
        self._toggle.toggled.connect(partial(self._on_toggled, body))
        vbox.addWidget(body)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        vbox.addWidget(line)

    def _on_toggled(self, body: QWidget, expanded: bool) -> None:
        """Fold/undfold, keep the arrow pointing the right way, and tell the page."""
        body.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.toggled.emit(expanded)


def _meta_label(session) -> QLabel:
    """The right-hand muted line: when it was recorded, how many cars, and any caveat.

    The recorded time is also what tells two attempts at one slot apart, which is why the app
    numbers them nowhere (core invariant #5).
    """
    drivers = len(session.classification.entries) if session.classification else 0
    bits = [recorded_label(session.recorded_at),
            f"{drivers} driver" + ("s" if drivers != 1 else "")]
    if session.classification is not None and session.classification.is_reconstructed:
        # say so: this result was rebuilt from telemetry because no Final Classification
        # packet arrived, so positions can differ from what the game acutally showed.
        bits.append("reconstructed")
    meta = QLabel("  ·  ".join(bits))
    meta.setStyleSheet(MUTED_TEXT_QSS)
    return meta


def _summary_row(session, label: str, name_of) -> QWidget:
    """One compact line - muted keys, normal values, pipe separators.

    A single row rather than a key/value block: the track is already in the card header or the
    page's, so repeating it bought nothing but height, and an overview is meant to be scannable.
    """
    body = QWidget()
    row = QHBoxLayout(body)
    row.setContentsMargins(24, 2, 0, 6)
    row.setSpacing(6)
    for index, (key, value) in enumerate(_summary_fields(session, label, name_of)):
        if index:
            row.addWidget(_muted("|"))
        row.addWidget(_muted(f"{key}:"))
        row.addWidget(value if isinstance(value, QWidget) else QLabel(value))
    row.addStretch(1)
    return body


def _summary_fields(session, label: str, name_of) -> list[tuple[str, object]]:
    """Key/value pairs for the summary line; a value may be a widget (the weather icon)."""
    fields: list[tuple[str, object]] = [("Session", label)]
    # "Winner" for every session type: a practice or qualifying session's winner is whoever
    # ended up P1, which is what the classification's first already is.
    leader = session_leader(session, name_of)
    if leader is not None:
        fields.append(("Winner", leader))
    fastest = session_fastest_lap(session, name_of)
    if fastest is not None:
        fields.append(("Fastest lap", fastest))
    fields.append(("Weather", WeatherIcon(session_weather(session), size_px=22)))
    difficulty = _ai_difficulty(session)
    if difficulty is not None:
        fields.append(("AI difficulty", difficulty))
    return fields


def _ai_difficulty(session) -> str | None:
    """The AI difficulty, an em dash when it wasn't captured, or nothing at all.

    ``ai_difficulty == 0`` is ambiguous on its own: it means both "no AI in this session"
    and "stored before PIPELINE_VERSION 3, so never read from the packet". ``is_ai`` on the
    classification entries tells the two apart - a full-human league session has no
    difficulty to show and gets no field, while a session that *did* run AI shows an em dash
    until a re-ingest fills the real number in.
    """
    if session.ai_difficulty:
        return str(session.ai_difficulty)
    entries = session.classification.entries if session.classification else ()
    return "\u2014" if any(entry.is_ai for entry in entries) else None


def _muted(text: str) -> QLabel:
    """A muted label for the summary row's keys and separators.
    
    ``MUTED_TEXT_QSS`` sets ``color:`` explicitly, which is the one kind of stylesheet A4 leaves
    alone - it can't freeze a colour it states outright (core invariant #11).
    """
    label = QLabel(text)
    label.setStyleSheet(MUTED_TEXT_QSS)
    return label
