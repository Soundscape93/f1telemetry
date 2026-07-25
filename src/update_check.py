"""Notify-only update check against GitHub Releases (no self-update yet).

Pure and Qt-free so it is trivially unit-testable: the only I/O os an injectable ``urlopen``.
``check_for_update`` NEVER raises - every network, rate-limit, or malformed-response failure
is folded into a :class:`CheckStatus.ERROR` result with a message. The app keeps working fully
offline; this only runs when a user clicks "Check for updates".
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum, auto

from .version import __version__

log = logging.getLogger(__name__)

# -- Configuration ---------------------------------------------------------------------------
GITHUB_OWNER = "Soundscape93"
GITHUB_REPO = "f1telemetry"
# When False (default) only *stable* releases are seen (GitHub's /releases/latest excludes drafts + prereleases).
# Flip to true to also surface prereleases (e.g. for testing new features via /releases list).
# Note: through this decision tester build must be published as a full Release, not "prerelease"/"draft"
INCLUDE_PRERELEASES = False

_TIMEOUT = 6.0 # seconds
_USER_AGENT = f"f1telemetry/{__version__}"
_NOTES_LIMIT = 600                          # chars of release body shown in the dialog


def _api_latest() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _api_list() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=20"


def releases_page() -> str:
    """Human readable releases page, used as a fallback download link."""
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def is_configured() -> bool:
    return bool(GITHUB_OWNER) and GITHUB_OWNER != "REPLACE_ME"


class CheckStatus(Enum):
    UP_TO_DATE = auto()
    UPDATE_AVAILABLE = auto()
    ERROR = auto()


@dataclass(frozen=True)
class ReleaseInfo:
    version: str           # tag, e.g. "v0.2.0"
    name: str               # release title
    notes: str              # body (may be truncated for display)
    html_url: str           # release page to open in the browser
    is_prerelease: bool


@dataclass(frozen=True)
class UpdateCheckResult:
    status: CheckStatus
    release: ReleaseInfo | None = None
    message: str | None = None


_ERROR_MSG = "Could not check for updates. Please try again later."


# --- version comparison (tiny SemVer; no external dependency) -------------------------------

def _version_key(text: str) -> tuple[int, int, int, int] | None:
    """(major, minor, patch, rank) or None if unparesable."""
    s = text.strip().lstrip("vV")
    if not s:
        return None
    core, _, pre = s.partition("-")
    core = core.split("+", 1)[0]
    parts = core.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        if not p.isdigit():
            return None
        nums.append(int(p))
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2], 0 if pre else 1)  # rank=0 for stable, 1 for prerelease


def is_newer(candidate: str, current: str) -> bool:
    """True iff ``candidate`` is a stricly newer version than ``current``."""
    ck, cur = _version_key(candidate), _version_key(current)
    if not ck or not cur:
        return False
    return ck > cur


# --- fetch ------------------------------------------------------------------------------

def _fetch_json(url: str, urlopen, timeout: float):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _release_from_json(obj: dict) -> ReleaseInfo:
    tag = obj["tag_name"]       # KeyError here -> caught -> ERROR
    notes = obj.get("body", "").strip()
    if len(notes) > _NOTES_LIMIT:
        notes = notes[:_NOTES_LIMIT].rstrip() + "…"
    return ReleaseInfo(
        version=tag,
        name=obj.get("name") or tag,
        notes=notes,
        html_url=obj.get("html_url") or releases_page(),
        is_prerelease=bool(obj.get("prerelease")),
    )


def _latest_from_list(items: list) -> ReleaseInfo | None:
    for obj in items:                   # GitHub returns newest first
        if obj.get("draft"):
            continue
        if obj.get("prerelease") and not INCLUDE_PRERELEASES:
            continue
        return _release_from_json(obj)
    return None


def check_for_update(current_version: str = __version__,
                     *, urlopen=urllib.request.urlopen,
                     timeout: float = _TIMEOUT) -> UpdateCheckResult:
    """Query GitHub Releases and compare with ``current_version``. Never raises."""
    if not is_configured():
        return UpdateCheckResult(
            CheckStatus.ERROR, message="Update checks aren't configured for this build."
        )
    try:
        if INCLUDE_PRERELEASES:
            release = _latest_from_list(_fetch_json(_api_list(), urlopen, timeout))
        else:
            release = _release_from_json(_fetch_json(_api_latest(), urlopen, timeout))
    except urllib.error.HTTPError as exc:
        # 404 (no releases yet), 403 (rate-limited), etc. - all non-fatal.
        log.info("Update check HTTP error %s", exc)
        return UpdateCheckResult(CheckStatus.ERROR, message=_ERROR_MSG)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:        # offline / DNS / timeout
        log.info("Update check network error: %s", exc)
        return UpdateCheckResult(CheckStatus.ERROR, message=_ERROR_MSG)
    except (ValueError, KeyError, TypeError) as exc:            # malformed JSON / shape
        log.info("Update check bad response: %s", exc)
        return UpdateCheckResult(CheckStatus.ERROR, message=_ERROR_MSG)
    except Exception as exc:  # belt-and-suspenders
        log.warning("Update check unexpected error: %s", exc)
        return UpdateCheckResult(CheckStatus.ERROR, message=_ERROR_MSG)
    
    if release is None:
        return UpdateCheckResult(CheckStatus.ERROR, message=_ERROR_MSG)
    if is_newer(release.version, current_version):
        return UpdateCheckResult(CheckStatus.UPDATE_AVAILABLE, release=release)
    return UpdateCheckResult(CheckStatus.UP_TO_DATE)
