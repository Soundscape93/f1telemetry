"""Shared confirm-and-delete for a stored session, used by every surface that offers it.

The dialogs live here and the write lives in ``pipeline.delete_session``, so the two entry
points - the weekend page's capture picker and the Sessions surface - cannot drift apart on
either half: ine confirmation wording, one refusal message, one write path. ``components/`` is
the neutral home; putting it under ``ui/sessions/`` would make a seasons page import from a
sibling surface.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ...pipeline import delete_session


def _season_phrase(season) -> str:
    """'Season 1' / 'Season 1 (“Wednesday League”)' - enough to go and find it.

    Deliberately not ``ui.seasons.labels.season_title``: ``components/`` must not depend on a
    surface package, and a refusal only needs to *identify* the season, not title it.
    """
    if season is None:
        return "another season"
    return f"Season {season.number}" + (f" (“{season.nickname}”)" if season.nickname else "")

def confirm_and_delete(parent, session_uid: int, session_store, season_store, lap_store=None) -> bool:
    """Confirm, then delete a session's stored results. True if anything was actually deleted.

    Returns False for a cancel *and* for a refusal - the caller only needs to know whether to
    re-read. The refusal is never swallowed silently: it names the season and round, because
    "it didn't delete" with no reason is indistinguishable from a bug.
    """
    confirm = QMessageBox.question(
        parent,
        "Delete session",
        "Delete this session's stored results from the database?\n\n"
        "The original recording in captures/ is kept, but this session will be skipped if you "
        "re-ingest that capture (it's remembered as deleted). Its laps and their saved traces "
        "are removed with it.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return False

    outcome = delete_session(session_uid, session_store, season_store, lap_store=lap_store)
    if outcome.refused_assigned:
        season = season_store.get_season(outcome.season_id)
        QMessageBox.warning(
            parent,
            "Session is assigned",
            f"This session is assigned to round {outcome.round_number} of "
            f"{_season_phrase(season)}, so it was not deleted.\n\n"
            "Unassign it from that round first, then delete it. Deleting it here would leave "
            "the round pointing at a session that no longer exists, and quietly drop its "
            "result from the standings.",
        )
    return outcome.deleted
