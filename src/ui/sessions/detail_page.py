"""The session detail page - one session's classification, and deliberately nothing more.

A header identifying the session, the capture it was ingested from, and the shared
classification table. Everything a full session detail might eventually hold - lap list, charts,
tabs, comparison, round assignment - is **out of scope and not to be invented here**; the layout
below the table is left empty on purpose until it is actually specified.

The table is ``components.build_classification_table``, the same builder the weekend page uses,
so the results grid can never drift between the two surfaces. "Source capture" is the one
capture-shaped thing this surface shows: ``recorded_by`` and the rest belong to a captures
surface, because one session can live in two files with different values and there is no single
truthful answer for a session row.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import paths
from ...domain.season import slot_for_session
from ...pipeline import resolve_capture_path
from ...protocol.reference import game_mode_name, track_name
from ..components import build_classification_table, clear_layout, confirm_and_delete
from ..formatting import recorded_label, slot_label, weather_label
from ..style import MUTED_TEXT_QSS, apply_heading


class DetailPage(QWidget):
    """One captured session: what it was, where it came from, and how it finished."""

    overview_requested = Signal()
    sessions_changed = Signal()

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._captures = capture_store
        self._laps = lap_store
        self._session_uid: str | None = None

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Sessions")
        back.clicked.connect(self.overview_requested.emit)
        self._title = QLabel()
        apply_heading(self._title, size_px=20)
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        self._recorded = QLabel()
        self._recorded.setStyleSheet(MUTED_TEXT_QSS)
        header.addWidget(self._recorded)
        outer.addLayout(header)

        self._subtitle = QLabel()
        self._subtitle.setStyleSheet(MUTED_TEXT_QSS)
        # The uid is here to be copied into a bug report, so it has to be selectable.
        self._subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._subtitle)

        source_row = QHBoxLayout()
        self._source = QLabel()
        self._source.setStyleSheet(MUTED_TEXT_QSS)
        source_row.addWidget(self._source)
        source_row.addStretch(1)
        delete = QPushButton("Delete...")
        delete.clicked.connect(self._on_delete)
        source_row.addWidget(delete)
        outer.addLayout(source_row)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def load(self, session_uid: str) -> None:
        """Populate the page for one session uid."""
        self._session_uid = str(session_uid)
        self.reload()

    def reload(self) -> None:
        """Re-query the session and rebuild; leave for the overview if it has vanished."""
        clear_layout(self._body)
        session, slot = self._current()
        if session is None:
            self.overview_requested.emit()      # deleted underneath us, or a re-ingest dropped it
            return

        label = slot_label(slot.session_type, slot.is_sprint_race)
        self._title.setText(f"{track_name(session.track_id)} — {label}")
        self._recorded.setText(recorded_label(session.recorded_at))
        self._subtitle.setText(self._subtitle_text(session))
        self._source.setText(f"Source capture: {self._capture_label(session)}")
        self._body.addWidget(
            build_classification_table(session, is_sprint_race=slot.is_sprint_race))
        self._body.addStretch(1)

    def _current(self):
        """The loaded session and its weekend slot, or ``(None, None)`` if it is gone.

        ``slot_for_session`` needs the other sessions of the weekend to tell a Sprint Race from
        the Grand Prix (core invariant #5), so the whole list is read either way.
        """
        if self._session_uid is None:
            return None, None
        all_sessions = self._sessions.list_sessions()
        session = next(
            (s for s in all_sessions if str(s.session_uid) == self._session_uid), None)
        if session is None:
            return None, None
        return session, slot_for_session(session, all_sessions)

    @staticmethod
    def _subtitle_text(session) -> str:
        """Weather · laps · game mode · uid. The uid is shown on purpose - a bug report needs it."""
        bits = [weather_label(session.weather)]
        if session.total_laps:
            bits.append(f"{session.total_laps} laps")
        bits.append(game_mode_name(session.game_mode))
        bits.append(f"uid {session.session_uid}")
        return "  ·  ".join(bits)

    def _capture_label(self, session) -> str:
        """Which archive this session came from, or an honest note about why it can't say.

        Three distinct answers, because they mean different things to a user: no capture row at
        all (pruned, or ingested before capture metadata was recorded), a row whose archive has
        moved or been deleted, and the normal case. The middle one is exactly what blocks a
        restore later, so it must not read the same as the first.
        """
        if self._captures is None:
            return "—"
        metas = self._captures.for_session(str(session.session_uid))
        if not metas:
            return "not recorded"
        captures_dir = str(paths.captures_dir())
        found = sorted(m.file_name for m in metas
                       if resolve_capture_path(m, captures_dir) is not None)
        if not found:
            return f"{metas[0].file_name}  (archive not found)"
        return ", ".join(found)

    def _on_delete(self) -> None:
        """Delete this session through the shared guard, then leave - this page has no subject."""
        if self._session_uid is None:
            return
        if not confirm_and_delete(self, int(self._session_uid), self._sessions, self._seasons,
                                  lap_store=self._laps):
            return
        self.sessions_changed.emit()
        self.overview_requested.emit()
