"""The sessions overview - foldable per-session cards over every stored session.

One collapsible card per captured session, newest first: the header carries the track and
session label, a delete action, and a muted recorded-time / driver-count line. Expanding a card
reveals a single compact summary row - session, leader, fastest lap, weather, AI difficulty -
and double-clicking the title opens the session's detail page.

Mirrors ``ui/laps/overview_page.py`` on purpose: same card idiom, same expansion set surviving a
re-filter, same A4b rules (no font-bearing stylesheet, ``apply_bold`` / ``MUTED_TEXT_QSS``). The
difference is what a card holds - the laps overview lists a session's laps and reads LapStore,
this summarises the session itself and never does, so the whole page costs one query.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget
)

from ...domain.season import slot_for_session
from ...protocol.reference import track_name
from ..components import WeatherIcon, clear_layout, confirm_and_delete
from ..formatting import (
    recorded_label,
    session_fastest_lap,
    session_leader,
    slot_label,
    weather_label
)
from ..style import MUTED_TEXT_QSS, apply_bold, apply_heading


class _TitleButton(QToolButton):
    """The card's fold/unfold title, which also opens the session on a double-click."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        """Open the session, undoing the fold the first click of the pair already caused.

        A checkable button toggles on the first press/release of a double-click, well before the
        double-click event arrives - so the card would fold or unfold on its way to opening the
        session. Toggling back restores the state the user actually left it in, and ``toggled``
        fires again, so ``_expanded`` and the row's visibility stay correct with no extra
        bookkeeping. Exactly one stray toggle needs undoing: the *second* release lands with the
        button no longer 'down', so ``QAbstractButton`` ignores it.
        """
        super().mouseDoubleClickEvent(event)
        self.setChecked(not self.isChecked())
        self.double_clicked.emit()


class OverviewPage(QWidget):
    """Foldable per-session summary cards with a track / session filter."""

    session_requested = Signal(str)  # session_uid (str, uint64-safe)
    sessions_changed = Signal()  # a delete removed stored data - other surfaces re-read
    deleted_requested = Signal()  # open the deleted-sessions manager (the container hops)

    def __init__(self, session_store, season_store, lap_store=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._lap_store = lap_store
        self._expanded: set[str] = set()  # uids whose card is open (survives a re-filter)
        self._query =  ""

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Sessions")
        apply_heading(title, size_px=20)
        header.addWidget(title)
        header.addStretch(1)
        # Always shown, cound and all - it is the only route to the manager and "(0)" is the
        # honest answer rather than a button that appears and disappears.
        self._deleted = QPushButton()
        self._deleted.setToolTip(
            "Sessions you deleted: what was removed, and how to bring one back")
        self._deleted.clicked.connect(self.deleted_requested.emit)
        header.addWidget(self._deleted)
        outer.addLayout(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by track or session")
        self._search.textChanged.connect(self._on_search)
        outer.addWidget(self._search)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    # --- filters ---------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self.reload()

    # --- build -----------------------------------------------------------
    def reload(self) -> None:
        """Rebuild the cards from the session store, honouring the current filter."""
        clear_layout(self._body)
        self._deleted.setText(f"Deleted sessions ({len(self._sessions.deleted_sessions())})")
        all_sessions = self._sessions.list_sessions()      # already recorded_at desc
        shown = 0
        for session in all_sessions:
            slot = slot_for_session(session, all_sessions)
            label = slot_label(slot.session_type, slot.is_sprint_race)
            track = track_name(session.track_id)
            if self._query and self._query not in f"{track} {label}".lower():
                continue
            self._body.addWidget(self._session_card(session, track, label))
            shown += 1
        if shown == 0:
            empty = QLabel(self._empty_message())
            empty.setStyleSheet(MUTED_TEXT_QSS)
            self._body.addWidget(empty)
        self._body.addStretch(1)

    def _empty_message(self) -> str:
        if self._query:
            return "No sessions match the filter."
        return "No sessions stored yet - record one, or import a capture from Help."

    def _session_card(self, session, track: str, label: str) -> QWidget:
        """A collapsible card: header line always, the summary row when expanded."""
        uid = str(session.session_uid)
        card = QFrame()
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        toggle = _TitleButton()
        toggle.setCheckable(True)
        toggle.setChecked(uid in self._expanded)
        toggle.setText(f"{track} — {label}")
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if toggle.isChecked() else Qt.ArrowType.RightArrow
        )
        # No stylesheet - it would freeze the button's text colour at apply time (A4b).
        toggle.setAutoRaise(True)
        apply_bold(toggle)
        toggle.setMinimumHeight(toggle.sizeHint().height() + 4)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setToolTip("Click to fold, double-click to open the session")
        toggle.double_clicked.connect(partial(self.session_requested.emit, uid))
        header.addWidget(toggle)

        delete = QToolButton()
        delete.setText("Delete…")
        delete.setAutoRaise(True)       # sits beside the title, so it must not shout
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setToolTip("Delete this session's stored results (the recording is kept)")
        delete.clicked.connect(partial(self._delete, int(session.session_uid)))
        header.addWidget(delete)

        header.addStretch(1)
        header.addWidget(self._meta_label(session))
        vbox.addLayout(header)

        summary = self._summary_row(session, label)
        summary.setVisible(toggle.isChecked())
        toggle.toggled.connect(partial(self._toggle_card, uid, summary, toggle))
        vbox.addWidget(summary)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        vbox.addWidget(line)
        return card

    def _meta_label(self, session) -> QLabel:
        """The right-hand muted line: when it was recorded, how many cars, and any caveat."""
        drivers = len(session.classification.entries) if session.classification else 0
        bits = [recorded_label(session.recorded_at),
                f"{drivers} driver" + ("s" if drivers != 1 else "")]
        if session.classification is not None and session.classification.is_reconstructed:
            # Say so: this result was rebuilt from telemetry because no Final Classification
            # packet arrived, so positions can differ from what the game actually showed.
            bits.append("reconstructed")
        meta = QLabel("  ·  ".join(bits))
        meta.setStyleSheet(MUTED_TEXT_QSS)
        return meta

    def _summary_row(self, session, label: str) -> QWidget:
        """One compact line - muted keys, normal values, pipe separators.

        A single row rather than a key/value block: the track is already in the card header, so
        repeating it bought nothing but height, and an overview is meant to be scannable.
        """
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(24, 2, 0, 6)
        row.setSpacing(6)
        for index, (key, value) in enumerate(self._summary_fields(session, label)):
            if index:
                row.addWidget(_muted("|"))
            row.addWidget(_muted(f"{key}:"))
            row.addWidget(value if isinstance(value, QWidget) else QLabel(value))
        row.addStretch(1)
        return body

    def _summary_fields(self, session, label: str) -> list[tuple[str, object]]:
        """Key/value pairs for the summary line; a value may be a widget (the weather icon)."""
        fields: list[tuple[str, object]] = [("Session", label)]
        # "Winner" for every session type: a practice or qualifying session's winner is whoever
        # ended up P1, which is what the classification's first entry already is.
        leader = session_leader(session)
        if leader is not None:
            fields.append(("Winner", leader))
        fastest = session_fastest_lap(session)
        if fastest is not None:
            fields.append(("Fastest lap", fastest))
        fields.append(("Weather", WeatherIcon(session.weather, size_px=22)))
        difficulty = self._ai_difficulty(session)
        if difficulty is not None:
            fields.append(("AI difficulty", difficulty))
        return fields

    @staticmethod
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
        return "—" if any(entry.is_ai for entry in entries) else None

    def _toggle_card(self, uid: str, summary: QWidget, toggle: QToolButton,
                     expanded: bool) -> None:
        summary.setVisible(expanded)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self._expanded.add(uid)
        else:
            self._expanded.discard(uid)

    def _delete(self, session_uid: int) -> None:
        """Delete through the shared guard, then tell the window and re-query.

        A refusal or a cancel changes nothing, so neither needs a reload - and the refusal
        message (which names the season and round) has already been shown by the shared helper.
        """
        if not confirm_and_delete(self, session_uid, self._sessions, self._seasons,
                                  lap_store=self._lap_store):
            return
        self.sessions_changed.emit()
        self.reload()


def _muted(text: str) -> QLabel:
    """A muted label for the summary row's keys and separators.

    ``MUTED_TEXT_QSS`` sets ``color:`` explicitly, which is the one kind of stylesheet A4 leaves
    alone - it can't freeze a colour it states outright (core invariant #11).
    """
    label = QLabel(text)
    label.setStyleSheet(MUTED_TEXT_QSS)
    return label
