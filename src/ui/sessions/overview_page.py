"""The sessions overview - foldable per-session cards over every stored session.

One collapsible card per captured session, newest first: the header carries the track and
session label with a muted recorded-time / driver-count line, and expanding reveals a short
summary - what the session was, who won it, its fastest lap, the AI difficulty it ran at - plus
the actions that apply to a whole session. A search box filters cards by track / session label.

Mirrors ``ui/laps/overview_page.py`` on purpose: same card idiom, same expansion set surviving a
re-filter, same A4b rules (no font-bearing stylesheet, ``apply_bold`` / ``MUTED_TEXT_QSS``). The
difference is what a card holds - the laps overview lists a session's laps and reads LapStore,
this summarises the session itself and never does, so the whole page costs one query.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
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
from ..components import clear_layout, confirm_and_delete
from ..formatting import (
    race_winner_summary,
    recorded_label,
    session_fastest_lap,
    slot_label,
    weather_label
)
from ..style import MUTED_TEXT_QSS, apply_bold, apply_heading


class OverviewPage(QWidget):
    """Foldable per-session summary cards with a track / session filter."""

    session_requested = Signal(str)  # session_uid (str, uint64-safe)
    sessions_changed = Signal()  # a delete removed stored data - other surfaces re-read

    def __init__(self, session_store, season_store, lap_store=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._lap_store = lap_store
        self._expanded: set[str] = set()  # uids whose card is open (survives a re-filter)
        self._query =  ""

        outer = QVBoxLayout(self)

        title = QLabel("Sessions")
        apply_heading(title, size_px=20)
        outer.addWidget(title)

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

    # --- filters ----------------------------------------------------------------------
    def _on_search(self, text: str):
        self._query = text.strip().lower()
        self._reload()

    # --- build --------------------------------------------------------------------------------
    def reload(self):
        """Rebuild the cards from the session store, honouring the current filter."""
        clear_layout(self._body)
        all_sessions = self._sessions.list_sessions()       # already recorded_at desc
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
        """A collapsible card: the header line always, summary + actions when expanded."""
        uid = str(session.session_uid)
        card = QFrame()
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        toggle.setChecked(uid in self._expanded)
        toggle.setText(f"{track} — {label}")
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if toggle.isChecked() else Qt.ArrowType.RightArrow
        )
        # No sytlesheet - it would freeze the button's text colour at apply time.
        toggle.setAutoRaise(True)
        apply_bold(toggle)
        toggle.setMinimumHeight(toggle.sizeHint().height() + 4)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(toggle)
        header.addStretch(1)
        header.addWidget(self._meta_label(session))
        vbox.addLayout(header)

        details = self._card_details(session, track, label)
        details.setVisible(toggle.isChecked())
        toggle.toggled.connect(partial(self._toggle_card, uid, details, toggle))
        vbox.addWidget(details)

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
            bits.append("reconstructed")
        meta = QLabel("  ·  ".join(bits))
        meta.setStyleSheet(MUTED_TEXT_QSS)
        return meta

    def _card_details(self, session, track: str, label: str) -> QWidget:
        """The expanded summary: a key/value block, then the per-session actions.
        
        Deliberalty a from of labels and not a ``QTableWidget`` - this is an overview, and a
        table here would read as the results grid that the detail page actually owns.
        """
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 4, 0, 8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setContentsMargins(0, 0, 0, 0)
        for key, value in self._summary_rows(session, track, label):
            key_label = QLabel(key)
            key_label.setStyleSheet(MUTED_TEXT_QSS)
            form.addRow(key_label, QLabel(value))
        layout.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch(1)
        open_btn = QPushButton("Open session")
        open_btn.clicked.connect(
            partial(self.session_requested.emit, str(session.session_uid)))
        actions.addWidget(open_btn)
        delete_btn = QPushButton("Delete...")
        delete_btn.clicked.connect(partial(self._delete, int(session.session_uid)))
        actions.addWidget(delete_btn)
        layout.addLayout(actions)
        return body

    def _summary_rows(self, session, track: str, label: str) -> list[tuple[str, str]]:
        """The key/value pairs for one card, omitting whatever this session can't answer."""
        session_bits = [label, track]
        if session.total_laps:
            session_bits.append(f"{session.total_laps} laps")
        session_bits.append(weather_label(session.weather))
        rows = [("Session", "  ·  ".join(session_bits))]

        winner = race_winner_summary(session)
        if winner is not None:
            rows.append(("Winner", winner))
        fastest = session_fastest_lap(session)
        if fastest is not None:
            rows.append(("Fastest lap", fastest))
        difficulty = self._ai_difficulty_row(session)
        if difficulty is not None:
            rows.append(difficulty)
        return rows

    @staticmethod
    def _ai_difficulty_row(session) -> tuple[str, str] | None:
        """The AI difficulty row, an em dash when it wasn't captured or no row at all.
        
        ``ai_difficulty == 0`` is ambiguous on its own: it means both "no AI in this session"
        and "stored before PIPELINE_VERSION 3, so never read from the packet". ``is_ai`` on the
        classification entries tells the two apart - a full-human league session has no
        difficulty to show and gets no row, while a session that *did* run AI shows an em dash
        until a re-ingest fills the real number in.
        """
        if session.ai_difficulty:
            return ("AI difficulty", str(session.ai_difficulty))
        entries = session.classification.entries if session.classification else []
        if any(entry.is_ai for entry in entries):
            return ("AI difficulty", "—")
        return None

    def _toggle_card(self, uid: str, details: QWidget, toggle: QToolButton, expanded: bool) -> None:
        details.setVisible(expanded)
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
        if not confirm_and_delete(self, session_uid, self._sessions, self._seasons, lap_store=self.lap_store):
            return
        self.sessions_changed.emit()
        self.reload()